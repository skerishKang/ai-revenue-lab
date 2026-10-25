"""#4434: the Resident lane that revises an approved XLSX workcopy after the ACK.

The real resident coordinator, the real canonical P01 file authority, real disk
and real workbook bytes; only the pinned broker transport is the in-memory shape
the sibling Office test already uses. No Drive, no model call, no live network.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import inspect
import os
import tempfile
import unittest

from kagent.contracts import ContractError
from kagent.local_agent_control_plane_https import ControlPlaneHttpsOperation
from kagent.local_agent_permissions import default_device_permission_profile
from kagent.local_agent_runtime_host import InMemorySingleInstanceLock
from kagent.local_agent_secure_transport import (
    OutboundBrokerEndpoint, OutboundTransportConfig, OutboundTransportMode,
)
from kagent.local_office_chunk_publisher import LocalOfficeChunkPublisher
from kagent.local_resident_xlsx_revision_delivery import (
    ResidentXlsxRevisionStager, TrustedP01XlsxRevisionBridge,
    TrustedP01XlsxRevisionPlan, compose_resident_xlsx_revision_stager,
)
from kagent.local_xlsx_python_copy_editor import PythonXlsxValueCopyEditor
from kagent.local_xlsx_workcopy_roundtrip import revised_path_for
from kagent.windows_local_filesystem import (
    DeterministicFakeWindowsFileAuthorizationPort, LocalFileOperation,
)

from test_4434_local_xlsx_workcopy_roundtrip import (
    EDIT, TEXT_EDIT, device, evidence_for, file_request, workbook_bytes,
)
from test_local_agent_runtime_host import _harness

ROOT_REF = "xlsx_root"
SOURCE_PATH = "quote\\book.xlsx"
DERIVED_PATH = revised_path_for(SOURCE_PATH)
DEVICE_ID = "dev_host_1"
WORKSPACE = "ws_host_1"
CREDENTIAL = b"resident-device-credential"
CONFIG = OutboundTransportConfig(endpoint=OutboundBrokerEndpoint(
    endpoint_ref="broker.resident.4434", url="https://broker.example.test/",
    mode=OutboundTransportMode.HTTPS_LONG_POLL,
))


class RecordingTransport:
    def __init__(self, broker=None, *, deny=False) -> None:
        self.broker = broker
        self.calls: list[dict] = []
        self.deny = deny

    def post(self, *, config, operation, payload, timeout_seconds):
        assert config.endpoint.url.startswith("https://")
        assert operation is ControlPlaneHttpsOperation.OFFICE_PART
        if self.broker is not None:
            # Nothing may be staged before the broker acknowledged the command.
            assert self.broker._commands["cmd_host_1"].state.value == "acknowledged"
        self.calls.append(payload)
        if self.deny:
            return {"ok": False, "error": {"code": "office_part_rejected"}}
        return {"ok": True, "office_part": {
            "stored": True, "kind": payload["kind"],
            "part_index": payload["part_index"],
        }}


class FollowClock:
    """Ticks just after the acknowledgement the lane was handed."""

    def __init__(self) -> None:
        self._now = datetime(2026, 10, 26, 0, 0, tzinfo=timezone.utc)

    def follow(self, acknowledged_at: datetime) -> None:
        self._now = acknowledged_at + timedelta(seconds=1)

    def __call__(self) -> datetime:
        return self._now


class PlanSource:
    """A deployment-shaped P01 revision source built from real local files."""

    def __init__(self, *, root: str, edits, off=False, tamper=None,
                 clock: "FollowClock | None" = None) -> None:
        self.root = root
        self.edits = tuple(edits)
        self.off = off
        self.tamper = tamper
        self.clock = clock
        self.calls: list[tuple[str, str]] = []
        self.context: dict[str, object] = {}

    def approved_revision_plan(self, *, binding, command, receipt):
        self.calls.append((binding.binding_ref, command.command_id))
        self.context = {"binding": binding, "command": command, "receipt": receipt}
        if self.off:
            return None
        fact = receipt.execution
        at = receipt.acknowledged_at
        if self.clock is not None:
            # The lane runs on the host clock; a test harness acknowledges a
            # command whose timestamp is a fixed simulated instant.
            self.clock.follow(at)
        read_request = file_request(
            LocalFileOperation.READ, path_relative=SOURCE_PATH,
            action_id=f"read_{command.command_id}",
            device_id=binding.device_id, root_ref=ROOT_REF, run_id=command.run_id,
            at=at,
        )
        with open(os.path.join(self.root, "quote", "book.xlsx"), "rb") as handle:
            source_bytes = handle.read()
        revised = PythonXlsxValueCopyEditor().revise_xlsx_copy(source_bytes, self.edits)
        if self.tamper is not None:
            revised = self.tamper(revised)
        write_request = file_request(
            LocalFileOperation.WRITE, path_relative=DERIVED_PATH,
            action_id=f"write_{command.command_id}", content=revised,
            device_id=binding.device_id, root_ref=ROOT_REF, run_id=command.run_id,
            at=at,
        )
        return TrustedP01XlsxRevisionPlan(
            binding_ref=binding.binding_ref, command_id=command.command_id,
            tool_request_ref=command.tool_request_ref, run_id=command.run_id,
            request_id=fact.request_id, revision_ref=command.revision_ref,
            command_fingerprint=fact.request_fingerprint, sequence=command.sequence,
            read_request=read_request,
            read_evidence=evidence_for(read_request, at=at),
            write_request=write_request,
            write_evidence=evidence_for(write_request, at=at),
            edits=self.edits,
        )


def revision_source_factory():
    """Importable trusted factory used only to prove the environment shape."""
    return PlanSource(root=tempfile.gettempdir(), edits=(EDIT,))


def _stager(root: str, *, transport: RecordingTransport, source: PlanSource,
            clock: FollowClock):
    profile = device(root, device_id=DEVICE_ID, workspace_ref=WORKSPACE, root_ref=ROOT_REF)
    return compose_resident_xlsx_revision_stager(
        device=profile, revision_plan_source=source,
        permission_profile=default_device_permission_profile(device=profile),
        publisher_config=CONFIG, transport=transport, clock=clock,
    )


@unittest.skipUnless(os.name == "nt", "the resident revision lane writes real files")
class ResidentXlsxRevisionLaneTests(unittest.TestCase):
    def setUp(self) -> None:
        InMemorySingleInstanceLock.reset()
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = self._directory.name
        os.makedirs(os.path.join(self.root, "quote"), exist_ok=True)
        self.source = os.path.join(self.root, "quote", "book.xlsx")
        self.result = os.path.join(self.root, "quote", "book_revised.xlsx")
        self.workbook = workbook_bytes()
        with open(self.source, "wb") as handle:
            handle.write(self.workbook)
        self.source_sha = sha256(self.workbook).hexdigest()

    def tearDown(self) -> None:
        InMemorySingleInstanceLock.reset()

    def _run(self, *, edits=(EDIT, TEXT_EDIT), deny=False, off=False, tamper=None):
        host, runtime, port, clock = _harness()
        follower = FollowClock()
        source = PlanSource(root=self.root, edits=edits, off=off, tamper=tamper,
                             clock=follower)
        transport = RecordingTransport(port.broker_authority, deny=deny)
        stager = _stager(self.root, transport=transport, source=source, clock=follower)
        host._xlsx_revision_staging = stager
        host.start()
        clock.advance(5)
        answered = host.run_once(now=clock.now)
        host.stop()
        return {
            "host": host, "runtime": runtime, "port": port, "transport": transport,
            "source": source, "stager": stager, "answered": answered, "clock": clock,
        }

    def _disk_sha(self, path: str) -> str:
        with open(path, "rb") as handle:
            return sha256(handle.read()).hexdigest()

    def test_acknowledged_revision_writes_a_new_file_and_stages_it(self) -> None:
        result = self._run()
        self.assertEqual(result["answered"], 1)
        self.assertEqual(result["runtime"].executed, ["req_host_1"])
        self.assertEqual(result["source"].calls, [("bind_host_1", "cmd_host_1")])
        self.assertTrue(os.path.isfile(self.result))
        self.assertEqual(self._disk_sha(self.source), self.source_sha)
        written = self._disk_sha(self.result)
        parts = result["transport"].calls
        self.assertEqual([p["kind"] for p in parts], ["xlsx"])
        self.assertEqual(parts[0]["command_id"], "cmd_host_1")
        self.assertEqual(parts[0]["run_id"], "run_host_1")
        self.assertTrue(parts[0]["artifact_id"].startswith("resident_xlsx_revision_result_"))
        self.assertEqual(parts[0]["filename"], "book_revised.xlsx")
        for forbidden in ("path", "account_ref", "workspace_ref", "destination"):
            self.assertNotIn(forbidden, parts[0])

    def test_one_acknowledged_command_is_revised_exactly_once(self) -> None:
        result = self._run()
        context = result["source"].context
        self.assertEqual(len(result["transport"].calls), 1)
        with self.assertRaises(ContractError):
            result["stager"].on_acknowledged(
                binding=context["binding"], command=context["command"],
                receipt=context["receipt"], credential=CREDENTIAL,
            )
        self.assertEqual(len(result["transport"].calls), 1)
        self.assertEqual(result["runtime"].executed, ["req_host_1"])
        self.assertEqual(result["port"].broker_authority._commands["cmd_host_1"].state.value,
                         "acknowledged")

    def test_a_second_revision_of_the_same_source_cannot_overwrite_the_result(self) -> None:
        first = self._run()
        result_bytes = self._disk_sha(self.result)
        self.assertTrue(first["transport"].calls)
        second = self._run()
        self.assertEqual(second["transport"].calls, [])
        self.assertEqual(self._disk_sha(self.result), result_bytes)
        self.assertEqual(self._disk_sha(self.source), self.source_sha)

    def test_non_revision_command_stages_nothing(self) -> None:
        result = self._run(off=True)
        self.assertEqual(result["answered"], 1)
        self.assertEqual(result["transport"].calls, [])
        self.assertFalse(os.path.exists(self.result))
        self.assertEqual(self._disk_sha(self.source), self.source_sha)

    def test_result_bytes_outside_the_approval_are_refused_before_any_write(self) -> None:
        result = self._run(tamper=lambda data: data + b"x")
        self.assertEqual(result["answered"], 1)
        self.assertEqual(result["transport"].calls, [])
        self.assertFalse(os.path.exists(self.result))
        self.assertEqual(result["port"].broker_authority._commands["cmd_host_1"].state.value,
                         "acknowledged")
        self.assertEqual(result["runtime"].executed, ["req_host_1"])

    def test_staging_refusal_keeps_the_acknowledged_command_truth(self) -> None:
        result = self._run(deny=True)
        self.assertEqual(len(result["transport"].calls), 1)
        self.assertEqual(result["port"].broker_authority._commands["cmd_host_1"].state.value,
                         "acknowledged")
        self.assertEqual(result["runtime"].executed, ["req_host_1"])
        self.assertTrue(os.path.isfile(self.result))

    def test_formula_source_is_routed_away_without_writing_or_staging(self) -> None:
        with open(self.source, "wb") as handle:
            handle.write(workbook_bytes(formula=True))
        result = self._run()
        self.assertEqual(result["transport"].calls, [])
        self.assertFalse(os.path.exists(self.result))
        self.assertEqual(result["port"].broker_authority._commands["cmd_host_1"].state.value,
                         "acknowledged")

    def test_fake_file_grant_cannot_enter_the_production_lane(self) -> None:
        profile = device(self.root, device_id=DEVICE_ID, workspace_ref=WORKSPACE,
                         root_ref=ROOT_REF)
        source = PlanSource(root=self.root, edits=(EDIT,))
        with self.assertRaises(ContractError):
            ResidentXlsxRevisionStager(
                device=profile,
                bridge=TrustedP01XlsxRevisionBridge(source=source),
                file_authorization_port=DeterministicFakeWindowsFileAuthorizationPort(),
                publisher=LocalOfficeChunkPublisher(transport=RecordingTransport(),
                                                    config=CONFIG),
                clock=FollowClock(),
            )

    def test_bridge_shape_correlation_and_one_shot_are_enforced(self) -> None:
        with self.assertRaises(ContractError):
            TrustedP01XlsxRevisionBridge(source=object())
        bridge = TrustedP01XlsxRevisionBridge(source=PlanSource(
            root=self.root, edits=(EDIT,),
        ))
        with self.assertRaises(ContractError):
            bridge.resolve("short")
        shape = bridge.safe_dict()
        self.assertIs(shape["approval_authority_created"], False)
        self.assertIs(shape["one_shot"], True)
        self.assertIs(shape["browser_file_plan_accepted"], False)
        self.assertEqual(shape["pending_evidence_count"], 0)


class ResidentXlsxRevisionCompositionTests(unittest.TestCase):
    def test_environment_names_only_a_trusted_factory_and_fails_closed(self) -> None:
        from kagent.local_agent_resident_process import (
            XLSX_REVISION_PLAN_SOURCE_ENV, xlsx_revision_plan_source_from_environment,
        )

        saved = os.environ.pop(XLSX_REVISION_PLAN_SOURCE_ENV, None)
        try:
            self.assertIsNone(xlsx_revision_plan_source_from_environment())
            for value, expectation in (
                ("definitely_missing_module_xyz:make", None),
                ("kagent.contracts:ContractError", None),
                ("no_colon_at_all", None),
                ("test_4434_resident_xlsx_revision_lane:revision_source_factory", "source"),
            ):
                os.environ[XLSX_REVISION_PLAN_SOURCE_ENV] = value
                resolved = xlsx_revision_plan_source_from_environment()
                with self.subTest(value=value):
                    if expectation is None:
                        self.assertIsNone(resolved)
                    else:
                        self.assertTrue(callable(resolved.approved_revision_plan))
        finally:
            os.environ.pop(XLSX_REVISION_PLAN_SOURCE_ENV, None)
            if saved is not None:
                os.environ[XLSX_REVISION_PLAN_SOURCE_ENV] = saved

    def test_lane_is_off_unless_a_trusted_source_is_composed(self) -> None:
        from kagent.local_agent_resident_process import build_resident_host
        from kagent.local_agent_runtime_host import LocalAgentResidentRuntimeHost

        host_params = inspect.signature(LocalAgentResidentRuntimeHost.__init__).parameters
        process_params = inspect.signature(build_resident_host).parameters
        self.assertIn("xlsx_revision_staging", host_params)
        self.assertIn("xlsx_revision_plan_source", process_params)
        self.assertIsNone(host_params["xlsx_revision_staging"].default)
        self.assertIsNone(process_params["xlsx_revision_plan_source"].default)

    def test_the_composition_builds_the_canonical_editor_verifier_publisher(self) -> None:
        """Nothing in the Resident's revision lane is a stand-in.

        The lane the host composes is the one function that runs the file
        operations, and its collaborators are the same Windows editor,
        independent verifier, canonical chunk publisher and P01 authority the
        standalone roundtrip test uses. A synthetic root path is enough here:
        this proves *composition*, and the lane test proves execution.
        """
        from kagent.local_xlsx_workcopy_roundtrip import (
            revise_and_stage_approved_xlsx_workcopy,
        )
        from kagent.local_xlsx_python_copy_editor import (
            IndependentZipXlsxRevisionVerifier, PythonXlsxValueCopyEditor,
        )
        from kagent.windows_local_filesystem import (
            P01LocalPermissionWindowsFileAuthorizationPort,
            WindowsSelectedRootFileRuntime,
        )

        signature = inspect.signature(revise_and_stage_approved_xlsx_workcopy)
        self.assertIsNone(signature.parameters["editor"].default)
        self.assertIsNone(signature.parameters["verifier"].default)
        self.assertIn("PythonXlsxValueCopyEditor", signature.parameters["editor"].annotation)
        self.assertIn("IndependentZipXlsxRevisionVerifier",
                      signature.parameters["verifier"].annotation)
        # Omitted collaborators are resolved by the roundtrip module itself, so
        # the names it binds are the editors and verifiers the lane can run.
        import kagent.local_xlsx_workcopy_roundtrip as roundtrip_module

        self.assertIs(roundtrip_module.PythonXlsxValueCopyEditor, PythonXlsxValueCopyEditor)
        self.assertIs(roundtrip_module.IndependentZipXlsxRevisionVerifier,
                      IndependentZipXlsxRevisionVerifier)

        profile = device("C:\\synthetic\\4434-root", device_id=DEVICE_ID,
                         workspace_ref=WORKSPACE, root_ref=ROOT_REF)
        stager = compose_resident_xlsx_revision_stager(
            device=profile,
            revision_plan_source=PlanSource(root="C:\\synthetic\\4434-root", edits=(EDIT,)),
            permission_profile=default_device_permission_profile(device=profile),
            publisher_config=CONFIG, transport=RecordingTransport(), clock=FollowClock(),
        )

        self.assertIsInstance(stager, ResidentXlsxRevisionStager)
        self.assertIsInstance(stager._publisher, LocalOfficeChunkPublisher)
        self.assertIsInstance(stager._runtime, WindowsSelectedRootFileRuntime)
        self.assertIsInstance(
            stager._runtime._authorization, P01LocalPermissionWindowsFileAuthorizationPort,
        )
        self.assertIs(type(stager._runtime._authorization),
                      P01LocalPermissionWindowsFileAuthorizationPort)

    def test_the_original_workcopy_is_never_the_write_target(self) -> None:
        """The lane derives a new name; the invariant is checked, not assumed."""
        from kagent.local_resident_xlsx_revision_delivery import (
            XLSX_REVISION_WRITES_THE_ORIGINAL,
        )

        self.assertIs(XLSX_REVISION_WRITES_THE_ORIGINAL, False)
        self.assertNotEqual(SOURCE_PATH, DERIVED_PATH)
        self.assertEqual(os.path.dirname(DERIVED_PATH), os.path.dirname(SOURCE_PATH))

if __name__ == "__main__":
    unittest.main()
