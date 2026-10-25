"""#4434: the Chat producer's output is the Resident consumer's input, byte for byte.

No HTTP, no Broker and no network. One mint is built from a server-shaped owner
proof, admitted by the Broker store validator, admitted by the Resident validator,
and then fed to the actual Resident plan source, which produces the plan the lane
executes. The refusals are the point: foreign owner, out-of-root path, non-literal
edit, missing proof, drifted confirmation, expired preview — and the fact that no
write digest or write approval can leave this server at all.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.connector_txt_approval_material import OwnerTxtApprovalProof
from app.connector_xlsx_revision_approval_material import (
    XlsxRevisionMaterialError, derived_result_path, mint_xlsx_revision_envelope,
    normalize_revision_edits, normalize_revision_path, preview_digest,
)
from app.connector_xlsx_revision_routes import (
    XLSX_REVISION_PREVIEW_PATH, XLSX_REVISION_REQUEST_PATH, RevisionPreviewStore,
    _body, _PREVIEW_KEYS, _REQUEST_KEYS,
)

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
EXECUTABLE = "C:\\Program Files\\PADIEM\\padiem-agent.exe"
ROOT = "quote_root"
PATH = "quote\\book.xlsx"
EDITS = [{"cell": "B2", "previous_value": 88_000_000, "replacement_value": 91_500_000}]


def proof(**overrides) -> OwnerTxtApprovalProof:
    values = {
        "owner_id": "usr_4434", "workspace_id": "cws_4434", "device_id": "dev_4434",
        "binding_ref": "bind_4434", "credential_generation": 3,
        "consent_id": "consent_4434", "run_id": "run_4434",
    }
    values.update(overrides)
    return OwnerTxtApprovalProof(**values)


def mint(**overrides):
    kwargs = {
        "approval": proof(), "root_ref": ROOT, "path_relative": PATH,
        "sheet_name": "Quote", "edits": [dict(item) for item in EDITS],
        "executable_path": EXECUTABLE, "now": NOW,
    }
    kwargs.update(overrides)
    return mint_xlsx_revision_envelope(**kwargs)


def minted_envelope():
    return mint()["envelope"]


class TestMintedEnvelope:
    def test_the_envelope_is_admitted_by_the_broker_and_the_resident(self) -> None:
        """One contract, three implementations, no translation layer."""

        from kagent.local_agent_command_material import (
            validate_xlsx_revision_receipt as resident_validate,
        )
        from local_agent_broker_material_store import (
            validate_xlsx_revision_receipt as store_validate,
        )

        envelope = minted_envelope()
        stored = store_validate(dict(envelope))
        resolved = resident_validate(dict(envelope))

        assert stored == resolved
        assert envelope["format"] == resolved["format"] == "claw-xlsx-revision-approval.v1"

    def test_the_envelope_carries_no_write_approval_and_no_result_digest(self) -> None:
        envelope = minted_envelope()

        assert set(envelope) == {
            "format", "evidence_ref", "command_id", "request_id", "local_policy_ref",
            "expires_at", "source_approval", "revision",
        }
        args = envelope["source_approval"]["exact_tool_arguments"]
        assert args["operation"] == "read"
        assert args["content_bytes"] == 0
        assert args["content_sha256"] is None
        assert set(envelope["revision"]) == {
            "sheet_name", "edits", "result_path_relative", "write_action_id",
            "write_requested_at",
        }
        assert "result_content_sha256" not in envelope["revision"]

    def test_the_read_attestation_binds_the_request_the_resident_recomputes(self) -> None:
        from kagent.windows_local_filesystem import (
            LocalFileOperation, LocalFileRequest, file_request_fingerprint,
            windows_file_tool_invocation,
        )
        from padiem_ai_core.agent_approval import tool_invocation_digest

        envelope = minted_envelope()
        args = envelope["source_approval"]["exact_tool_arguments"]
        request = LocalFileRequest(
            action_id=args["action_id"], run_id=args["run_id"],
            device_id=args["device_id"], root_ref=args["root_ref"],
            operation=LocalFileOperation.READ, path_relative=args["path_relative"],
            requested_at=datetime.fromisoformat(args["requested_at"].replace("Z", "+00:00")),
        )

        assert args["request_fingerprint"] == file_request_fingerprint(request)
        assert (envelope["source_approval"]["approval_pause"]["invocation_sha256"]
                == tool_invocation_digest(windows_file_tool_invocation(request)))

    def test_the_material_is_the_closed_command_shape_the_broker_stores(self) -> None:
        issued = mint()

        assert issued["material"]["shell_authority"] is False
        assert issued["material"]["admin_elevation"] is False
        assert issued["material"]["environment_payload"] is None
        assert issued["material"]["provider_authority"] is None
        assert issued["material"]["p01_approval_payload"] is issued["envelope"]
        assert issued["enqueue"]["request_fingerprint"]
        assert issued["material"]["timeout_seconds"] == 30

    def test_the_result_name_is_always_the_derived_copy_never_the_original(self) -> None:
        issued = mint()

        assert issued["preview"]["result_path_relative"] == "quote\\book_revised.xlsx"
        assert issued["preview"]["result_path_relative"] != PATH
        assert derived_result_path(PATH) == "quote\\book_revised.xlsx"


class TestResidentConsumption:
    """The minted envelope has to survive the actual consumer, not just validators."""

    def _ack(self, command, request_fingerprint, request_id):
        from kagent.local_agent_command_admission import (
            AdmittedLocalCommandExecutionReceipt,
        )
        from kagent.local_agent_control_plane_admission import (
            ControlPlaneAdmittedExecutionReceipt,
        )
        from kagent.windows_local_executor import WindowsExecutionTermination

        execution = AdmittedLocalCommandExecutionReceipt(
            admission_ref="admission_4434_producer", command_id=command.command_id,
            tool_request_ref=command.tool_request_ref, sequence=command.sequence,
            session_id="session_4434_producer", binding_ref=command.binding_ref,
            request_id=request_id, run_id=command.run_id,
            request_fingerprint=request_fingerprint,
            assembly_ref="assembly_4434_producer",
            authorization_ref="authorization_4434_producer",
            termination=WindowsExecutionTermination.EXITED, exit_code=0,
            revision_ref=command.revision_ref,
        )
        return ControlPlaneAdmittedExecutionReceipt(
            execution=execution, evidence_ref="evidence_ack_4434_producer",
            acknowledged_at=NOW + timedelta(seconds=5),
        )

    def _binding_and_command(self, issued):
        from kagent.local_agent_pairing import (
            DeviceBinding, DeviceCommandEnvelope, DeviceLifecycle,
        )

        binding = DeviceBinding(
            device_id="dev_4434", binding_ref="bind_4434", account_ref="acct_4434",
            workspace_ref="cws_4434", credential_ref="cred_4434",
            credential_generation=3, issued_at=NOW - timedelta(minutes=5),
            credential_expires_at=NOW + timedelta(hours=1),
            state=DeviceLifecycle.ONLINE,
        )
        command = DeviceCommandEnvelope(
            command_id=issued["envelope"]["command_id"], run_id="run_4434",
            tool_request_ref=issued["enqueue"]["tool_request_ref"],
            binding_ref="bind_4434", sequence=1,
            issued_at=NOW - timedelta(minutes=1), expires_at=NOW + timedelta(minutes=5),
            revision_ref="revision_4434_producer",
        )
        return binding, command

    def _source(self):
        from kagent.verified_p01_xlsx_revision_plan_source import (
            P01EvidenceWriteAttester, VerifiedP01XlsxRevisionPlanSource,
        )

        def attester_factory(**scoped):
            return P01EvidenceWriteAttester(
                base_url="https://loopback.invalid", opener=lambda body: {}, **scoped)

        return VerifiedP01XlsxRevisionPlanSource(attester_factory=attester_factory)

    def test_a_minted_command_becomes_a_resident_plan(self) -> None:
        from kagent.local_resident_xlsx_revision_delivery import TrustedP01XlsxRevisionPlan

        issued = mint()
        envelope = issued["envelope"]
        binding, command = self._binding_and_command(issued)
        scoped = self._source()
        fingerprint = issued["enqueue"]["request_fingerprint"]

        assert scoped.note_admitted(
            binding=binding, command=command, request_id=envelope["request_id"],
            request_fingerprint=fingerprint, receipt=envelope) is True
        plan = scoped.approved_revision_plan(
            binding=binding, command=command,
            receipt=self._ack(command, fingerprint, envelope["request_id"]))

        assert isinstance(plan, TrustedP01XlsxRevisionPlan)
        assert plan.derived_path_relative == "quote\\book_revised.xlsx"
        assert plan.edits[0].replacement_value == 91_500_000
        assert plan.read_request.path_relative == PATH

    def test_a_command_that_carries_no_revision_envelope_gets_no_plan(self) -> None:
        issued = mint()
        binding, command = self._binding_and_command(issued)
        scoped = self._source()

        assert scoped.note_admitted(
            binding=binding, command=command, request_id=issued["envelope"]["request_id"],
            request_fingerprint="f" * 64, receipt=None) is False
        assert scoped.approved_revision_plan(
            binding=binding, command=command,
            receipt=self._ack(command, "f" * 64, issued["envelope"]["request_id"])) is None

    def test_an_envelope_made_for_another_device_never_reaches_a_plan(self) -> None:
        issued = mint(approval=proof(device_id="dev_other"))
        binding, command = self._binding_and_command(issued)
        scoped = self._source()
        envelope = issued["envelope"]

        with pytest.raises(Exception):
            scoped.note_admitted(
                binding=binding, command=command, request_id=envelope["request_id"],
                request_fingerprint=issued["enqueue"]["request_fingerprint"],
                receipt=envelope)


class TestProducerRefusals:
    def test_a_non_xlsx_selection_is_refused(self) -> None:
        with pytest.raises(XlsxRevisionMaterialError):
            normalize_revision_path("quote\\notes.txt")

    def test_paths_that_leave_the_selected_root_are_refused(self) -> None:
        for value in ("..\\work\\book.xlsx", "\\\\share\\book.xlsx", "C:\\x\\book.xlsx",
                      "/srv/book.xlsx"):
            with self_subtest(value), pytest.raises(XlsxRevisionMaterialError):
                normalize_revision_path(value)

    def test_only_literal_reviewed_edits_survive(self) -> None:
        for edits in (
            [{"cell": "B2", "previous_value": 1, "replacement_value": "=SUM(A1)"}],
            [{"cell": "B2", "previous_value": 1, "replacement_value": 1.5}],
            [{"cell": "B2", "previous_value": 1, "replacement_value": True}],
            [{"cell": "b2", "previous_value": 1, "replacement_value": 2}],
            [{"cell": "B2", "previous_value": 1}],
            [],
        ):
            with self_subtest(str(edits)), pytest.raises(XlsxRevisionMaterialError):
                normalize_revision_edits("Quote", edits)

    def test_an_untrusted_or_missing_executable_profile_is_refused(self) -> None:
        for value in (None, "", "python", "relative\\agent.exe",
                      "C:\\Program Files\\PADIEM\\agent.dll"):
            with self_subtest(repr(value)), pytest.raises(XlsxRevisionMaterialError):
                mint(executable_path=value)

    def test_a_forged_owner_proof_never_mints(self) -> None:
        with pytest.raises(XlsxRevisionMaterialError):
            mint_xlsx_revision_envelope(
                approval="dev_4434", root_ref=ROOT, path_relative=PATH,
                sheet_name="Quote", edits=[dict(item) for item in EDITS],
                executable_path=EXECUTABLE)

    def test_a_browser_body_outside_the_closed_shape_is_refused(self) -> None:
        import json as _json

        good = {"device_id": "dev_4434", "root_ref": ROOT, "path_relative": PATH,
                "sheet_name": "Quote", "edits": [dict(item) for item in EDITS],
                "run_id": "run_4434"}
        assert _body(_json.dumps(good).encode(), _PREVIEW_KEYS) is not None
        for extra in ({"credential_b64": "AAA"}, {"binding_ref": "bind_4434"},
                      {"confirmed": True}, {"account_ref": "acct_other"}):
            assert _body(_json.dumps({**good, **extra}).encode(), _PREVIEW_KEYS) is None
        assert _body(b"not json", _PREVIEW_KEYS) is None
        assert _body(_json.dumps({k: v for k, v in good.items() if k != "run_id"}).encode(),
                     _PREVIEW_KEYS) is None
        # The confirmation route demands the closed pair; the preview must not accept it.
        assert _body(_json.dumps({**good, "preview_ref": "p", "confirmed": True}).encode(),
                     _PREVIEW_KEYS) is None
        assert _body(_json.dumps({**good, "preview_ref": "p", "confirmed": True}).encode(),
                     _REQUEST_KEYS) is not None
        assert _body(_json.dumps({**good, "preview_ref": "p", "confirmed": False}).encode(),
                     _REQUEST_KEYS) is not None


class TestPreviewConfirmation:
    def _store(self, clock_value: list[datetime]) -> RevisionPreviewStore:
        return RevisionPreviewStore(clock=lambda: clock_value[0])

    def _record(self, store: RevisionPreviewStore) -> str:
        return store.record(
            owner_id="usr_4434", run_id="run_4434", device_id="dev_4434",
            root_ref=ROOT, path_relative=PATH, sheet_name="Quote",
            edits=[dict(item) for item in EDITS],
            preview={"sheet_name": "Quote", "edits": [dict(item) for item in EDITS],
                     "result_path_relative": "quote\\book_revised.xlsx"})

    def test_the_same_intent_confirms_once(self) -> None:
        now = [NOW]
        store = self._store(now)
        ref = self._record(store)

        entry = store.confirm(
            ref=ref, owner_id="usr_4434", run_id="run_4434", device_id="dev_4434",
            root_ref=ROOT, path_relative=PATH, sheet_name="Quote",
            edits=[dict(item) for item in EDITS])

        assert entry["preview"]["result_path_relative"] == "quote\\book_revised.xlsx"
        # One reference, one confirmation: the second call cannot re-approve.
        with pytest.raises(XlsxRevisionMaterialError):
            store.confirm(
                ref=ref, owner_id="usr_4434", run_id="run_4434", device_id="dev_4434",
                root_ref=ROOT, path_relative=PATH, sheet_name="Quote",
                edits=[dict(item) for item in EDITS])

    def test_an_edited_intent_between_preview_and_confirm_is_refused(self) -> None:
        now = [NOW]
        store = self._store(now)
        ref = self._record(store)
        changed = [{"cell": "B2", "previous_value": 88_000_000,
                    "replacement_value": 500_000}]

        with pytest.raises(XlsxRevisionMaterialError):
            store.confirm(
                ref=ref, owner_id="usr_4434", run_id="run_4434", device_id="dev_4434",
                root_ref=ROOT, path_relative=PATH, sheet_name="Quote", edits=changed)

    def test_another_owner_or_device_or_run_cannot_use_the_reference(self) -> None:
        now = [NOW]
        store = self._store(now)
        ref = self._record(store)
        base = {
            "ref": ref, "owner_id": "usr_4434", "run_id": "run_4434",
            "device_id": "dev_4434", "root_ref": ROOT, "path_relative": PATH,
            "sheet_name": "Quote", "edits": [dict(item) for item in EDITS],
        }
        for field, value in (("owner_id", "usr_other"), ("device_id", "dev_other"),
                             ("run_id", "run_other"), ("root_ref", "root_other")):
            with self_subtest(field), pytest.raises(XlsxRevisionMaterialError):
                store.confirm(**{**base, field: value})

    def test_an_expired_preview_is_gone(self) -> None:
        now = [NOW]
        store = self._store(now)
        ref = self._record(store)
        now[0] = NOW + timedelta(minutes=6)

        with pytest.raises(XlsxRevisionMaterialError):
            store.confirm(
                ref=ref, owner_id="usr_4434", run_id="run_4434", device_id="dev_4434",
                root_ref=ROOT, path_relative=PATH, sheet_name="Quote",
                edits=[dict(item) for item in EDITS])

    def test_the_store_keeps_no_envelope_and_no_secret(self) -> None:
        now = [NOW]
        store = self._store(now)
        self._record(store)
        shape = store.safe_dict()

        assert shape["envelope_stored"] is False
        assert shape["raw_values_stored"] is False
        assert shape["one_shot"] is True


def self_subtest(label):
    import contextlib

    return contextlib.nullcontext(label)


class TestMounting:
    def test_the_pair_is_mounted_on_the_existing_authority_precondition(self) -> None:
        """Registered beside the TXT lane, inside the same composition guard."""

        source = (Path(__file__).resolve().parents[1] / "app" / "app_factory.py"
                  ).read_text(encoding="utf-8")

        assert "XLSX_REVISION_PREVIEW_PATH, preview_revision, methods=[\"POST\"]" in source
        assert "XLSX_REVISION_REQUEST_PATH, request_revision, methods=[\"POST\"]" in source
        assert XLSX_REVISION_PREVIEW_PATH == "/api/claw/connector/xlsx-revisions/preview"
        assert XLSX_REVISION_REQUEST_PATH == "/api/claw/connector/xlsx-revisions/request"
        guard = source.split("if connector_owner_enrollment is not None:", 1)[1]
        assert "XLSX_REVISION_PREVIEW_PATH" in guard.split("if ", 1)[0][:4000]
