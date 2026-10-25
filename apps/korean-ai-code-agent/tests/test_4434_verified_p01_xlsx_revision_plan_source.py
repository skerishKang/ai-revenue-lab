"""#4434: the Resident's P01 XLSX revision plan source, on canonical material.

The real Engine approval objects, the real canonical file-request fingerprint and
the real tool-invocation digest. The P01 evidence boundary is an injected opener
because this test must not depend on a listening service; every shape it accepts
or refuses is checked against the same envelope the route would return.

Nothing here grants access, mints a decision or touches a customer file.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from padiem_ai_core.agent_approval import (
    ApprovalOutcome, ApprovalRequirement, VerifiedApprovalDecision,
)

from kagent.contracts import ContractError
from kagent.local_agent_command_material import XLSX_REVISION_POLICY_REF
from kagent.local_agent_command_admission import AdmittedLocalCommandExecutionReceipt
from kagent.local_agent_control_plane_admission import ControlPlaneAdmittedExecutionReceipt
from kagent.local_agent_pairing import DeviceBinding, DeviceCommandEnvelope, DeviceLifecycle
from kagent.local_resident_xlsx_revision_delivery import TrustedP01XlsxRevisionPlan
from kagent.verified_p01_xlsx_revision_plan_source import (
    P01EvidenceWriteAttester, VerifiedP01XlsxRevisionPlanSource,
    XLSX_REVISION_SOURCE_MINTS_APPROVAL, make_p01_xlsx_revision_plan_source,
)
from kagent.windows_local_filesystem import (
    LocalFileOperation, file_request_fingerprint,
)

from test_4434_xlsx_revision_receipt_contract import (
    DEVICE, REQUEST, RESULT_PATH, RUN, SOURCE_PATH, WRITE_ACTION, receipt,
)

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
ACKED = NOW + timedelta(seconds=10)
FINGERPRINT = "f" * 64
BINDING = "bind_4434_source"
COMMAND = "cmd_4434_receipt"


def _binding() -> DeviceBinding:
    return DeviceBinding(
        device_id=DEVICE, binding_ref=BINDING, account_ref="account_4434",
        workspace_ref="workspace_4434", credential_ref="cred_4434",
        credential_generation=1, issued_at=NOW - timedelta(minutes=5),
        credential_expires_at=NOW + timedelta(hours=1),
        state=DeviceLifecycle.ONLINE,
    )


def _command() -> DeviceCommandEnvelope:
    return DeviceCommandEnvelope(
        command_id=COMMAND, run_id=RUN, tool_request_ref="tool_4434",
        binding_ref=BINDING, sequence=1, issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=5), revision_ref="revision_4434",
    )


def _receipt(*, command_id=COMMAND, request_id=REQUEST, run_id=RUN,
             device_id=DEVICE, root_ref="quote_root", acknowledged_at=ACKED,
             result_path=RESULT_PATH):
    envelope = receipt()
    args = envelope["source_approval"]["exact_tool_arguments"]
    args["run_id"], args["device_id"], args["root_ref"] = run_id, device_id, root_ref
    envelope["command_id"] = command_id
    envelope["request_id"] = request_id
    envelope["revision"]["result_path_relative"] = result_path
    pause = envelope["source_approval"]["approval_pause"]
    pause["run_id"] = run_id
    pause["created_at"] = (acknowledged_at - timedelta(minutes=2)).isoformat().replace(
        "+00:00", "Z")
    pause["expires_at"] = (acknowledged_at + timedelta(minutes=3)).isoformat().replace(
        "+00:00", "Z")
    decision = envelope["source_approval"]["approval_decision"]
    decision["decided_at"] = (acknowledged_at - timedelta(minutes=1)).isoformat().replace(
        "+00:00", "Z")
    envelope["expires_at"] = (acknowledged_at + timedelta(minutes=3)).isoformat().replace(
        "+00:00", "Z")
    # The read half must bind the recomputed invocation of *this* request.
    from kagent.windows_local_filesystem import windows_file_tool_invocation
    from padiem_ai_core.agent_approval import tool_invocation_digest
    from test_4434_local_xlsx_workcopy_roundtrip import file_request
    read = file_request(LocalFileOperation.READ, path_relative=SOURCE_PATH,
                        action_id=args["action_id"], device_id=device_id,
                        root_ref=root_ref, run_id=run_id, at=acknowledged_at)
    args["requested_at"] = read.requested_at.isoformat().replace("+00:00", "Z")
    args["request_fingerprint"] = file_request_fingerprint(read)
    pause["invocation_sha256"] = tool_invocation_digest(
        windows_file_tool_invocation(read))
    envelope["revision"]["write_requested_at"] = acknowledged_at.isoformat().replace(
        "+00:00", "Z")
    return envelope


def source(opener=None):
    def attester_factory(**scoped):
        return P01EvidenceWriteAttester(opener=opener, base_url="", **scoped)

    return VerifiedP01XlsxRevisionPlanSource(attester_factory=attester_factory)


class AdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.binding, self.command = _binding(), _command()
        self.scoped = source()

    def _note(self, envelope, *, fingerprint=FINGERPRINT):
        return self.scoped.note_admitted(
            binding=self.binding, command=self.command, request_id=REQUEST,
            request_fingerprint=fingerprint, receipt=envelope,
        )

    def _plan(self):
        return self.scoped.approved_revision_plan(
            binding=self.binding, command=self.command, receipt=_ack_with(self.command))

    def test_a_revision_command_becomes_a_plan_with_two_independent_halves(self) -> None:
        self.assertIs(self._note(_receipt()), True)

        plan = self._plan()
        self.assertIsInstance(plan, TrustedP01XlsxRevisionPlan)
        self.assertIs(plan.read_request.operation, LocalFileOperation.READ)
        self.assertEqual(plan.derived_path_relative, RESULT_PATH)
        self.assertEqual(plan.write_action_id, WRITE_ACTION)
        self.assertEqual(len(plan.edits), 2)
        self.assertEqual(
            plan.read_evidence.request_fingerprint,
            file_request_fingerprint(plan.read_request),
        )

    def test_commands_without_revision_material_stay_on_their_own_path(self) -> None:
        for foreign in (None, {"format": "claw-txt-read-approval.v1"}, {}):
            with self.subTest(receipt=foreign):
                self.assertIs(self._note(foreign), False)

    def test_no_plan_exists_for_a_command_that_was_never_attested(self) -> None:
        plan = source().approved_revision_plan(
            binding=self.binding, command=self.command,
            receipt=_ack_with(self.command))
        self.assertIsNone(plan)

    def test_malformed_revision_material_stops_the_command_before_execution(self) -> None:
        broken = _receipt()
        broken["revision"]["edits"] = []
        with self.assertRaises(ContractError):
            self._note(broken)

        smuggled = _receipt()
        smuggled["result_approval"] = {"approval_pause": {}, "approval_decision": {},
                                      "exact_tool_arguments": {}}
        with self.assertRaises(ContractError):
            self._note(smuggled)

    def test_material_belonging_to_another_command_is_refused(self) -> None:
        for kwargs in ({"command_id": "cmd_other"}, {"request_id": "req_other"},
                      {"run_id": "run_other"}, {"device_id": "device_other"}):
            with self.subTest(**kwargs), self.assertRaises(ContractError):
                self._note(_receipt(**kwargs))

    def test_a_result_name_that_is_not_the_derived_copy_is_refused(self) -> None:
        with self.assertRaises(ContractError):
            other = _receipt(result_path="quote\\other.xlsx")
            scoped = source()
            scoped.note_admitted(
                binding=self.binding, command=self.command, request_id=REQUEST,
                request_fingerprint=FINGERPRINT, receipt=other)
            scoped.approved_revision_plan(
                binding=self.binding, command=self.command,
                receipt=_ack_with(self.command))

    def test_the_source_mints_no_approval_and_reads_no_file(self) -> None:
        self.assertIs(XLSX_REVISION_SOURCE_MINTS_APPROVAL, False)
        self.assertIs(source().safe_dict()["approval_authority_created"], False)
        self.assertIs(source().safe_dict()["write_attested_before_result_bytes"], False)


class DeferredWriteAttestationTests(unittest.TestCase):
    def _attester(self, *, mode="approve"):
        def opener(body: bytes) -> dict:
            from json import loads

            asked = loads(body.decode("utf-8"))
            fingerprint = asked["request_fingerprint"]
            if mode == "missing":
                return {}
            if mode == "wrong_key":
                fingerprint = "0" * 64
            return {"envelope": _write_envelope(fingerprint, mode=mode)}

        return P01EvidenceWriteAttester(
            base_url="https://loopback.invalid", command_id=COMMAND,
            binding_ref=BINDING, request_id=REQUEST, opener=opener,
            clock=lambda: ACKED + timedelta(seconds=5),
        )

    def _write_request(self):
        from test_4434_local_xlsx_workcopy_roundtrip import file_request
        return file_request(
            LocalFileOperation.WRITE, path_relative=RESULT_PATH,
            action_id=WRITE_ACTION, content=b"result-bytes", device_id=DEVICE,
            root_ref="quote_root", run_id=RUN, at=ACKED,
        )

    def test_the_boundary_can_attest_a_write_that_now_exists(self) -> None:
        attester = self._attester()
        request = self._write_request()

        evidence = attester.attest(request)

        self.assertEqual(evidence.request_fingerprint,
                         file_request_fingerprint(request))
        self.assertIs(evidence.approval_decision.outcome, ApprovalOutcome.APPROVED)
        self.assertIs(evidence.approval_pause.requirement,
                      ApprovalRequirement.USER_CONFIRMATION)
        self.assertEqual(evidence.local_policy_ref, XLSX_REVISION_POLICY_REF)

    def test_a_boundary_with_nothing_for_this_write_is_a_refusal(self) -> None:
        for mode in ("missing", "no_envelope", "wrong_key", "denied", "other_tool"):
            with self.subTest(mode=mode), self.assertRaises(ContractError):
                self._attester(mode=mode).attest(self._write_request())

    def test_one_attestation_is_spent_once(self) -> None:
        attester = self._attester()
        request = self._write_request()

        attester.attest(request)
        with self.assertRaises(ContractError):
            attester.attest(request)

    def test_a_boundary_without_a_configured_origin_refuses(self) -> None:
        attester = P01EvidenceWriteAttester(
            base_url="", command_id=COMMAND, binding_ref=BINDING, request_id=REQUEST)
        with self.assertRaises(ContractError):
            attester.attest(self._write_request())


class EnvironmentCompositionTests(unittest.TestCase):
    def test_the_pinned_name_resolves_to_a_source_the_resident_accepts(self) -> None:
        import os

        from kagent.local_agent_resident_process import (
            XLSX_REVISION_PLAN_SOURCE_ENV, xlsx_revision_plan_source_from_environment,
        )

        saved = os.environ.pop(XLSX_REVISION_PLAN_SOURCE_ENV, None)
        try:
            os.environ[XLSX_REVISION_PLAN_SOURCE_ENV] = (
                "kagent.verified_p01_xlsx_revision_plan_source"
                ":make_p01_xlsx_revision_plan_source")
            resolved = xlsx_revision_plan_source_from_environment()
        finally:
            os.environ.pop(XLSX_REVISION_PLAN_SOURCE_ENV, None)
            if saved is not None:
                os.environ[XLSX_REVISION_PLAN_SOURCE_ENV] = saved

        self.assertTrue(callable(resolved.approved_revision_plan))
        self.assertTrue(callable(resolved.note_admitted))
        self.assertIsInstance(resolved, VerifiedP01XlsxRevisionPlanSource)

    def test_the_factory_needs_no_path_no_credential_and_no_approval(self) -> None:
        self.assertIsInstance(make_p01_xlsx_revision_plan_source(),
                              VerifiedP01XlsxRevisionPlanSource)


def _write_envelope(fingerprint: str, *, mode="approve") -> dict:
    """The canonical envelope shape the resident's own evidence client parses."""

    from kagent.windows_local_filesystem import windows_file_tool_invocation
    from padiem_ai_core.agent_approval import tool_invocation_digest
    from test_4434_local_xlsx_workcopy_roundtrip import file_request

    if mode == "no_envelope":
        # An envelope that is present but incomplete still refuses the write.
        return {"evidence_ref": "evidence_partial"}
    request = file_request(LocalFileOperation.WRITE, path_relative=RESULT_PATH,
                           action_id=WRITE_ACTION, content=b"result-bytes",
                           device_id=DEVICE, root_ref="quote_root", run_id=RUN, at=ACKED)
    digest = tool_invocation_digest(windows_file_tool_invocation(request))
    tool_id = "local.filesystem.write" if mode != "other_tool" else "local.filesystem.read"
    outcome = "approved" if mode != "denied" else "denied"
    return {
        "evidence_ref": "evidence_write_4434",
        "request_fingerprint": fingerprint,
        "approval_pause": {
            "pause_id": "pause_write_4434", "run_id": RUN,
            "agent_runtime_id": "agent_4434", "tool_id": tool_id,
            "invocation_sha256": digest, "requirement": "user_confirmation",
            "step_index": 2,
            "created_at": (ACKED - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
            "expires_at": (ACKED + timedelta(minutes=3)).isoformat().replace("+00:00", "Z"),
            "approval_scope": ["filesystem.write"],
        },
        "approval_decision": {
            "decision_id": "decision_write_4434", "pause_id": "pause_write_4434",
            "outcome": outcome,
            "authority_ref": "claw_connector_xlsx_revision_request_v1",
            "evidence_ref": "evidence_write_4434",
            "decided_at": ACKED.isoformat().replace("+00:00", "Z"),
        },
        "permission_requests": [{
            "action_id": WRITE_ACTION, "run_id": RUN, "device_id": DEVICE,
            "capability": "filesystem.write", "target_ref": fingerprint,
            "root_ref": "quote_root",
        }],
        "local_policy_ref": XLSX_REVISION_POLICY_REF,
        "expires_at": (ACKED + timedelta(minutes=3)).isoformat().replace("+00:00", "Z"),
    }


def _ack_with(command: DeviceCommandEnvelope) -> ControlPlaneAdmittedExecutionReceipt:
    from kagent.windows_local_executor import WindowsExecutionTermination

    execution = AdmittedLocalCommandExecutionReceipt(
        admission_ref="admission_4434", command_id=command.command_id,
        tool_request_ref=command.tool_request_ref, sequence=command.sequence,
        session_id="session_4434", binding_ref=command.binding_ref,
        request_id=REQUEST, run_id=command.run_id, request_fingerprint=FINGERPRINT,
        assembly_ref="assembly_4434", authorization_ref="authorization_4434",
        termination=WindowsExecutionTermination.EXITED, exit_code=0,
        revision_ref=command.revision_ref,
    )
    return ControlPlaneAdmittedExecutionReceipt(
        execution=execution, evidence_ref="evidence_ack_4434",
        acknowledged_at=ACKED,
    )


if __name__ == "__main__":
    unittest.main()
