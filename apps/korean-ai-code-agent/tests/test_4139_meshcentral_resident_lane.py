"""#4139 trial — ordered Resident lane over the private MeshCentral read.

Drives the REAL lane end to end: the canonical TXT approval receipt is minted
by the actual Chat issuance module (imported, not duplicated), the ordered
three host calls are exercised against a recording private read port and a
recording canonical text transport, and the live 113-byte trial body is the
authority. No live Broker, no MeshCentral server and no approval minted here.
"""
from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "apps" / "padiem-chat"))

from app.connector_txt_approval_material import (  # noqa: E402
    OwnerTxtApprovalProof,
    mint_txt_read_receipt,
)

from kagent.contracts import ContractError  # noqa: E402
from kagent.local_agent_command_admission import (  # noqa: E402
    AdmittedLocalCommandExecutionReceipt,
)
from kagent.local_agent_control_plane_admission import (  # noqa: E402
    ControlPlaneAdmittedExecutionReceipt,
)
from kagent.local_agent_meshcentral_private_reader import (  # noqa: E402
    MeshCentralReadRefused,
    MeshCentralVerifiedTextReader,
)
from kagent.local_agent_meshcentral_resident_lane import (  # noqa: E402
    MESHCENTRAL_LOGIN_USER_ENV,
    MESHCENTRAL_MESHCTRL_JS_ENV,
    MESHCENTRAL_PASSWORD_FILE_ENV,
    MESHCENTRAL_TRIAL_FILE_PATH_ENV,
    MESHCENTRAL_TRIAL_NODE_REF_ENV,
    MESHCENTRAL_TRIAL_PATH_RELATIVE_ENV,
    MESHCENTRAL_TRIAL_ROOT_REF_ENV,
    MeshCentralResidentTextLane,
    MeshCentralTrialTextMaterial,
    MeshCentralTrialTextTarget,
    SingleFileMeshCentralTrialTargetSource,
    compose_meshcentral_verified_text_delivery,
    make_meshcentral_trial_text_material,
)
from kagent.local_agent_pairing import (  # noqa: E402
    DeviceBinding,
    DeviceCommandEnvelope,
    DeviceLifecycle,
)
from kagent.local_agent_secure_transport import (  # noqa: E402
    OutboundBrokerEndpoint,
    OutboundTransportConfig,
    OutboundTransportMode,
)
from kagent.local_agent_verified_text_result import (  # noqa: E402
    MAX_VERIFIED_TEXT_RESULT_BYTES,
    LocalAgentTextResultPublisher,
    VerifiedTextResultRefused,
)
from kagent.local_resident_verified_text_delivery import (  # noqa: E402
    AdmittedTextReadContext,
)
from kagent.windows_local_executor import WindowsExecutionTermination  # noqa: E402

NOW = datetime(2026, 10, 16, 5, 0, 0, tzinfo=timezone.utc)
CREDENTIAL = b"synthetic-canonical-credential-v1"
FINGERPRINT = "b" * 64

#: The live 113-byte trial body (five LF terminators), byte-identical to the
#: verified trial artifact: 113 bytes, sha256 a8c2ead9...473c.
LIVE_TEXT = (
    b"PADIEM MESHCENTRAL SINGLE-PC TXT TEST\n"
    b"DATE=2026-10-16\n"
    b"HOST=COM1\n"
    b"TEST_CASE=mesh-agent-read-and-return\n"
    b"END_OF_FILE\n"
)
LIVE_SHA = "a8c2ead9ce5bb71a8e2625a482dd16be0196ef92df2af4e83156db45622b473c"

TRIAL_NODE = "node.trial.com1"
TRIAL_FILE = r"C:\Trial\meshcentral-padiem-trial.txt"
ROOT_REF = "root.docs"
PATH_RELATIVE = r"notes\report.txt"


def _binding():
    return DeviceBinding(
        device_id="device-1", binding_ref="binding-1", account_ref="acc-1",
        workspace_ref="ws-1", credential_ref="cred-1", credential_generation=1,
        issued_at=NOW - timedelta(hours=1),
        credential_expires_at=NOW + timedelta(hours=1),
        state=DeviceLifecycle.ONLINE,
    )


def _issued(**overrides):
    proof_args = {
        "owner_id": "owner-1",
        "workspace_id": "ws-1",
        "device_id": "device-1",
        "binding_ref": "binding-1",
        "credential_generation": 1,
        "consent_id": "consent-1",
        "run_id": "run-conversation-1",
    }
    proof_args.update(overrides.pop("proof", {}))
    path_relative = overrides.pop("path_relative", PATH_RELATIVE)
    return mint_txt_read_receipt(
        approval=OwnerTxtApprovalProof(**proof_args),
        root_ref=ROOT_REF,
        path_relative=path_relative,
        now=NOW,
        executable_path=r"C:\Program Files\Padiem\resident.exe",
        **overrides,
    )


def _command(issued):
    return DeviceCommandEnvelope(
        command_id=issued["receipt"]["command_id"],
        run_id="run-conversation-1",
        tool_request_ref=issued["tool_request_ref"],
        binding_ref="binding-1", sequence=1, issued_at=NOW,
        expires_at=NOW + timedelta(minutes=5), revision_ref="revision-1",
    )


def _admitted(issued):
    return AdmittedTextReadContext(
        admission_ref="admission-1",
        evidence_ref=issued["receipt"]["evidence_ref"],
        request_id=issued["material"]["request_id"],
        command_fingerprint=FINGERPRINT,
        admitted_at=NOW + timedelta(seconds=5),
    )


def _execution(issued, *, termination=WindowsExecutionTermination.EXITED, exit_code=0):
    return AdmittedLocalCommandExecutionReceipt(
        admission_ref="admission-1",
        command_id=issued["receipt"]["command_id"],
        tool_request_ref=issued["tool_request_ref"],
        sequence=1,
        session_id="session-1",
        binding_ref="binding-1",
        request_id=issued["material"]["request_id"],
        run_id="run-conversation-1",
        request_fingerprint=FINGERPRINT,
        assembly_ref="assembly-1",
        authorization_ref="authorization-1",
        termination=termination,
        revision_ref="revision-1",
        exit_code=exit_code,
    )


def _ack(issued, *, execution=None, evidence_ref="evidence-ack-1"):
    return ControlPlaneAdmittedExecutionReceipt(
        execution=execution or _execution(issued),
        evidence_ref=evidence_ref,
        acknowledged_at=NOW + timedelta(seconds=10),
    )


def _config():
    return OutboundTransportConfig(
        endpoint=OutboundBrokerEndpoint(
            endpoint_ref="broker.text.4139", url="https://broker.example.test/",
            mode=OutboundTransportMode.HTTPS_LONG_POLL,
        ),
    )


class RecordingTextPort:
    """The canonical text transport, recording the frame order it observed."""

    def __init__(self, *, order, refuse_pending=False):
        self.order = order
        self.refuse_pending = refuse_pending
        self.calls: list[dict] = []

    @property
    def states(self) -> list[str]:
        return [call["state"] for call in self.calls]

    def post(self, *, config, operation, payload, timeout_seconds):
        state = payload["state"]
        self.order.append(f"broker:{state}")
        self.calls.append(dict(payload))
        if state == "pending":
            if self.refuse_pending:
                return {"ok": False, "error": {"code": "text_result_not_admitted"}}
            return {"ok": True, "text_result": {
                "stored": True, "reused": False, "state": "pending",
                "content_present": False,
            }}
        return {"ok": True, "text_result": {
            "stored": True, "reused": False, "state": "content",
            "content_present": True,
        }}


class RecordingMeshPort:
    """The private MeshCentral read port, recording target and order."""

    def __init__(self, *, order, raw=LIVE_TEXT, fail=None):
        self.order = order
        self.raw = raw
        self.fail = fail
        self.calls: list[dict] = []

    def read_bytes(self, *, node_ref, file_path, timeout_seconds):
        self.order.append("mesh-read")
        self.calls.append({
            "node_ref": node_ref, "file_path": file_path,
            "timeout_seconds": timeout_seconds,
        })
        if self.fail is not None:
            raise self.fail
        return self.raw


class TrialLane:
    """The real lane over recording ports: order pinned from the inside."""

    def __init__(self, *, order=None, refuse_pending=False, mesh=None, source=None):
        self.order = order if order is not None else []
        self.transport = RecordingTextPort(order=self.order, refuse_pending=refuse_pending)
        self.mesh = mesh or RecordingMeshPort(order=self.order)
        self.issued = _issued()
        self.binding = _binding()
        self.command = _command(self.issued)
        self.admitted = _admitted(self.issued)
        self.source = source or SingleFileMeshCentralTrialTargetSource(
            target=MeshCentralTrialTextTarget(
                node_ref=TRIAL_NODE, file_path=TRIAL_FILE,
                root_ref=ROOT_REF, path_relative=PATH_RELATIVE,
            ),
        )
        self.lane = MeshCentralResidentTextLane(
            source=self.source,
            reader=MeshCentralVerifiedTextReader(
                publisher=LocalAgentTextResultPublisher(
                    transport=self.transport, config=_config(),
                ),
                port=self.mesh,
            ),
        )

    @property
    def payload(self):
        return self.issued["material"]["p01_approval_payload"]

    def declare(self, *, receipt="__issued__", command=None, admitted=None):
        return self.lane.declare_pending_for_admitted(
            binding=self.binding,
            command=command or self.command,
            admitted=admitted or self.admitted,
            credential=CREDENTIAL,
            receipt=self.payload if receipt == "__issued__" else receipt,
        )

    def read(self, *, execution=None):
        return self.lane.observe_approved_read(
            binding=self.binding, command=self.command,
            execution=execution or _execution(self.issued),
        )

    def deliver(self, *, ack=None):
        return self.lane.on_acknowledged(
            binding=self.binding, command=self.command,
            receipt=ack or _ack(self.issued), credential=CREDENTIAL,
        )

    def run(self):
        assert self.declare() is True
        assert self.read() is not None
        return self.deliver()


class OrderedMeshCentralLaneTests(unittest.TestCase):
    def test_pending_before_private_read_and_body_only_after_the_ack(self):
        lane = TrialLane()
        assert lane.declare() is True
        # Declared, and nothing has been read yet.
        self.assertEqual(lane.order, ["broker:pending"])
        self.assertEqual(lane.mesh.calls, [])

        result = lane.read()
        # The real private read happened, and no body has travelled yet.
        self.assertIsNotNone(result)
        self.assertEqual(lane.order, ["broker:pending", "mesh-read"])
        self.assertEqual(lane.mesh.calls[0]["node_ref"], TRIAL_NODE)
        self.assertEqual(lane.mesh.calls[0]["file_path"], TRIAL_FILE)

        delivery = lane.deliver()
        # The body travelled only after the successful ACK, as the bytes the
        # read produced — never re-read.
        self.assertIsNotNone(delivery)
        self.assertEqual(
            lane.order, ["broker:pending", "mesh-read", "broker:content"],
        )
        self.assertEqual(lane.mesh.calls and len(lane.mesh.calls), 1)
        pending, content = lane.transport.calls
        self.assertEqual(pending["state"], "pending")
        self.assertEqual(pending["request_fingerprint"], FINGERPRINT)
        self.assertEqual(content["state"], "content")
        self.assertEqual(content["content_bytes"], 113)
        self.assertEqual(content["content_sha256"], LIVE_SHA)
        self.assertEqual(content["content_utf8"], LIVE_TEXT.decode("utf-8"))
        safe = delivery.safe_dict()
        self.assertTrue(safe["returned_to_claw"])
        self.assertTrue(safe["content_present"])
        self.assertEqual(safe["content_sha256"], LIVE_SHA)
        self.assertFalse(safe["file_reread_after_ack"])

    def test_absent_receipt_keeps_the_ordinary_command_path(self):
        lane = TrialLane()
        # No TXT approval material: not a text read, nothing declared, nothing
        # read; the command keeps its ordinary execution path.
        self.assertFalse(lane.declare(receipt=None))
        self.assertEqual(lane.order, [])
        self.assertEqual(lane.mesh.calls, [])

    def test_foreign_receipt_is_refused_not_repurposed(self):
        lane = TrialLane()
        foreign = _issued(path_relative=r"notes\other.txt")
        with self.assertRaises(ContractError):
            lane.declare(
                receipt=foreign["material"]["p01_approval_payload"],
            )
        self.assertEqual(lane.order, [])
        self.assertEqual(lane.mesh.calls, [])

    def test_receipt_naming_another_file_than_the_trial_target_is_refused(self):
        lane = TrialLane()
        # Correlated receipt for this very command, but a different file: a
        # trial-scoped resident refuses instead of reading a foreign file.
        other = _issued(path_relative=r"notes\other.txt")
        with self.assertRaises(ContractError):
            lane.lane.declare_pending_for_admitted(
                binding=lane.binding, command=_command(other),
                admitted=_admitted(other), credential=CREDENTIAL,
                receipt=other["material"]["p01_approval_payload"],
            )
        self.assertEqual(lane.mesh.calls, [])

    def test_declare_refusal_stops_before_the_private_read(self):
        lane = TrialLane(refuse_pending=True)
        with self.assertRaises(VerifiedTextResultRefused):
            lane.declare()
        self.assertEqual(lane.order, ["broker:pending"])
        self.assertEqual(lane.mesh.calls, [])

    def test_failed_execution_produces_no_read_and_no_body(self):
        lane = TrialLane()
        assert lane.declare() is True
        self.assertIsNone(lane.read(execution=_execution(lane.issued, exit_code=1)))
        self.assertEqual(lane.mesh.calls, [])
        self.assertIsNone(lane.deliver())
        self.assertEqual(lane.order, ["broker:pending"])

    def test_read_refusal_is_never_a_completed_text_result(self):
        lane = TrialLane(mesh=RecordingMeshPort(order=[], raw=b""))
        assert lane.declare() is True
        with self.assertRaises(MeshCentralReadRefused):
            lane.read()
        # The command is not acknowledged as a successful read, and no body
        # can travel afterwards: only the declaration was left behind.
        self.assertIsNone(lane.deliver())
        self.assertEqual(lane.transport.states, ["pending"])

    def test_oversized_read_is_refused_never_truncated(self):
        lane = TrialLane(
            mesh=RecordingMeshPort(
                order=[], raw=b"x" * (MAX_VERIFIED_TEXT_RESULT_BYTES + 1),
            ),
        )
        assert lane.declare() is True
        with self.assertRaises(VerifiedTextResultRefused):
            lane.read()
        self.assertIsNone(lane.deliver())
        self.assertEqual(lane.transport.states, ["pending"])

    def test_body_only_after_an_exact_acknowledged_correlation(self):
        lane = TrialLane()
        assert lane.declare() is True
        assert lane.read() is not None
        wrong = _ack(lane.issued, execution=_execution(
            lane.issued, termination=WindowsExecutionTermination.TIMED_OUT,
        ))
        with self.assertRaises(ContractError):
            lane.deliver(ack=wrong)
        # A mismatched receipt never uploads content.
        self.assertEqual(lane.transport.states, ["pending"])

    def test_replay_resends_the_same_bytes_without_a_second_read(self):
        lane = TrialLane()
        delivery = lane.run()
        replayed = lane.lane.replay(
            delivery=delivery, binding_ref=lane.binding.binding_ref,
            credential=CREDENTIAL,
        )
        self.assertEqual(replayed["state"], "content")
        self.assertEqual(lane.transport.states, ["pending", "content", "content"])
        self.assertEqual(
            lane.transport.calls[1]["content_sha256"],
            lane.transport.calls[2]["content_sha256"],
        )
        self.assertEqual(len(lane.mesh.calls), 1)

    def test_second_answer_for_the_same_command_is_refused(self):
        lane = TrialLane()
        assert lane.declare() is True
        with self.assertRaises(ContractError):
            lane.declare()


class ComposedCliPortTests(unittest.TestCase):
    def test_compose_reads_the_staged_target_without_exposing_the_password(self):
        recorded = {}

        def runner(argv, *, input, timeout):
            recorded["argv"] = list(argv)
            recorded["input"] = input
            target = argv[argv.index("--target") + 1]
            Path(target).write_bytes(LIVE_TEXT)
            return types.SimpleNamespace(returncode=0)

        material = MeshCentralTrialTextMaterial(
            node_ref=TRIAL_NODE, file_path=TRIAL_FILE,
            root_ref=ROOT_REF, path_relative=PATH_RELATIVE,
            meshctrl_js="C:/meshcentral/meshctrl.js",
            login_user="trial-admin",
            password_provider=lambda: "synthetic-password",
            command_runner=runner,
        )
        order: list[str] = []
        transport = RecordingTextPort(order=order)
        lane = compose_meshcentral_verified_text_delivery(
            material=material, config=_config(), transport=transport,
        )
        issued = _issued()
        binding, command, admitted = _binding(), _command(issued), _admitted(issued)
        payload = issued["material"]["p01_approval_payload"]

        self.assertTrue(lane.declare_pending_for_admitted(
            binding=binding, command=command, admitted=admitted,
            credential=CREDENTIAL, receipt=payload,
        ))
        result = lane.observe_approved_read(
            binding=binding, command=command, execution=_execution(issued),
        )
        self.assertIsNotNone(result)
        delivery = lane.on_acknowledged(
            binding=binding, command=command, receipt=_ack(issued),
            credential=CREDENTIAL,
        )
        self.assertIsNotNone(delivery)
        self.assertEqual(delivery.result.content_bytes, 113)
        self.assertIsNotNone(delivery.result.content_sha256)
        # The real CLI port performs the read between the declaration and the
        # body; the recorded runner call below is its inside evidence.
        self.assertEqual(order, ["broker:pending", "broker:content"])

        argv = recorded["argv"]
        self.assertIn("download", argv)
        self.assertEqual(argv[argv.index("--id") + 1], TRIAL_NODE)
        self.assertEqual(argv[argv.index("--file") + 1], TRIAL_FILE)
        marker = argv[argv.index("--loginpass") + 1]
        self.assertTrue(marker.startswith("__PADIEM_MESHCTRL_PASSWORD_FROM_STDIN__"))
        # The password travels over the child's stdin only, never the argv.
        self.assertNotIn("synthetic-password", " ".join(argv))
        self.assertEqual(recorded["input"], "synthetic-password\n")

    def test_compose_refuses_incomplete_material(self):
        with self.assertRaises(ContractError):
            compose_meshcentral_verified_text_delivery(
                material=object(), config=_config(),
            )


class FactoryAndResolverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="padiem_mesh_trial_4139_")
        self.addCleanup(self.temp.cleanup)
        self.blob = Path(self.temp.name) / "operator.dpapi"
        self.blob.write_text("synthetic-dpapi-blob", encoding="utf-8")

    def _deployment_env(self):
        return {
            MESHCENTRAL_TRIAL_NODE_REF_ENV: TRIAL_NODE,
            MESHCENTRAL_TRIAL_FILE_PATH_ENV: TRIAL_FILE,
            MESHCENTRAL_TRIAL_ROOT_REF_ENV: ROOT_REF,
            MESHCENTRAL_TRIAL_PATH_RELATIVE_ENV: PATH_RELATIVE,
            MESHCENTRAL_MESHCTRL_JS_ENV: "C:/meshcentral/meshctrl.js",
            MESHCENTRAL_LOGIN_USER_ENV: "trial-admin",
            MESHCENTRAL_PASSWORD_FILE_ENV: str(self.blob),
        }

    def test_factory_requires_complete_deployment_material(self):
        deployment = self._deployment_env()
        with patch.dict(os.environ, deployment):
            material = make_meshcentral_trial_text_material()
        self.assertIsInstance(material, MeshCentralTrialTextMaterial)
        self.assertTrue(callable(material.target_for_admitted_command))
        self.assertTrue(callable(material.read_port))

        for missing in (MESHCENTRAL_TRIAL_FILE_PATH_ENV, MESHCENTRAL_PASSWORD_FILE_ENV):
            partial = dict(deployment)
            partial.pop(missing)
            with patch.dict(os.environ, partial, clear=False):
                os.environ.pop(missing, None)
                with self.assertRaises(ValueError, msg=missing):
                    make_meshcentral_trial_text_material()

        missing_file = dict(deployment)
        missing_file[MESHCENTRAL_PASSWORD_FILE_ENV] = str(
            Path(self.temp.name) / "absent.dpapi"
        )
        with patch.dict(os.environ, missing_file):
            with self.assertRaises(ValueError):
                make_meshcentral_trial_text_material()

    def test_resolver_is_off_by_default_and_shape_checked(self):
        from kagent.local_agent_resident_process import (
            MESHCENTRAL_TRIAL_TEXT_SOURCE_ENV,
            meshcentral_trial_text_material_from_environment,
        )

        os.environ.pop(MESHCENTRAL_TRIAL_TEXT_SOURCE_ENV, None)
        self.addCleanup(os.environ.pop, MESHCENTRAL_TRIAL_TEXT_SOURCE_ENV, None)
        self.assertIsNone(meshcentral_trial_text_material_from_environment())

        class _Material:
            def target_for_admitted_command(self, **kwargs):
                return None

            def read_port(self):
                return object()

        probe = types.ModuleType("kagent._mesh_trial_text_probe")
        probe.material = lambda: _Material()
        probe.no_port = lambda: types.SimpleNamespace(
            target_for_admitted_command=lambda **kwargs: None
        )
        probe.not_material = lambda: object()

        def _unimportable():
            raise ImportError("no material")

        probe.raises = _unimportable
        sys.modules[probe.__name__] = probe
        self.addCleanup(sys.modules.pop, probe.__name__, None)

        for value in (
            "",  # unset/blank
            "kagent._mesh_trial_text_probe",  # no factory attribute
            "kagent._mesh_trial_text_probe.not_material",  # wrong shape
            "kagent._mesh_trial_text_probe.no_port",  # half shape
            "kagent._mesh_trial_text_probe.raises",  # unimportable material
        ):
            os.environ[MESHCENTRAL_TRIAL_TEXT_SOURCE_ENV] = value
            self.assertIsNone(
                meshcentral_trial_text_material_from_environment(), value,
            )

        os.environ[MESHCENTRAL_TRIAL_TEXT_SOURCE_ENV] = (
            "kagent._mesh_trial_text_probe:material"
        )
        self.assertIsInstance(
            meshcentral_trial_text_material_from_environment(), _Material,
        )

    def test_resident_process_pins_the_trial_composition(self):
        source = (
            Path(__file__).parents[1] / "src" / "kagent" / "local_agent_resident_process.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "meshcentral_trial_text_material=meshcentral_trial_text_material_from_environment(),",
            source,
        )
        self.assertIn(
            "two competing verified text read authorities refused", source,
        )
        self.assertIn('event="verified_text_lane"', source)
        self.assertIn("meshcentral_private_trial", source)

    def test_live_trial_body_is_the_verified_113_byte_artifact(self):
        self.assertEqual(len(LIVE_TEXT), 113)
        self.assertEqual(sha256(LIVE_TEXT).hexdigest(), LIVE_SHA)
        self.assertEqual(LIVE_TEXT.count(b"\n"), 5)


if __name__ == "__main__":
    unittest.main()
