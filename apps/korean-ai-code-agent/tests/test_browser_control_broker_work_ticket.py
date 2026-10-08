"""#3782: broker/P01 action cross-correlation remains closed without an issuer."""
from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from kagent.browser_control_actions import BrowserControlActionRequest
from kagent.browser_control_broker_work_ticket import (
    BROKER_BROWSER_CONTROL_SOURCE_WIRED,
    DESKTOP_ACTION_DELIVERY_WIRED,
    AuthenticatedBrowserControlWorkTicket,
)
from kagent.browser_control_lease_authority import (
    BROWSER_CONTROL_TOOL_ID,
    BrowserControlAuthorityEvidence,
    BrowserControlLeaseRequest,
    BrowserControlP01CommandCorrelation,
)
from kagent.contracts import ContractError
from kagent.local_agent_pairing import (
    DeviceBinding,
    DeviceCommandEnvelope,
    DeviceLifecycle,
    DeviceSession,
)
from kagent.local_agent_permissions import LocalPermissionRequest
from padiem_ai_core.agent_approval import (
    ApprovalOutcome,
    ApprovalPause,
    ApprovalRequirement,
    VerifiedApprovalDecision,
)
from padiem_control_plane.local_agent_broker import BrokerCommandAdmission

NOW = datetime(2026, 10, 8, 11, 0, 0, tzinfo=timezone.utc)
MINUS = NOW - timedelta(minutes=1)
PLUS = NOW + timedelta(minutes=3)


def ticket() -> AuthenticatedBrowserControlWorkTicket:
    lease = BrowserControlLeaseRequest(
        browser_session_ref="browser.session.3782", run_ref="run.3782",
        workspace_ref="workspace.3782", owner_ref="owner.3782",
        device_id="device.3782", origin_scope="https://example.com",
        allowed_action_classes=("click",), ttl_seconds=120, max_actions=1,
    )
    fp = lease.fingerprint()
    command = DeviceCommandEnvelope(
        command_id="command.3782.control", run_id="run.3782",
        tool_request_ref="tool.3782", binding_ref="binding.3782",
        sequence=1, revision_ref="revision.3782",
        issued_at=MINUS, expires_at=PLUS,
    )
    binding = DeviceBinding(
        device_id="device.3782", binding_ref="binding.3782",
        account_ref="account.3782", workspace_ref="workspace.3782",
        credential_ref="credential.3782", credential_generation=1,
        issued_at=MINUS, credential_expires_at=PLUS,
    )
    session = DeviceSession(
        session_id="session.3782", device_id="device.3782",
        binding_ref="binding.3782", account_ref="account.3782",
        workspace_ref="workspace.3782", issued_at=MINUS, expires_at=PLUS,
    )
    admission = BrokerCommandAdmission(
        admission_ref="admission.3782", authority_ref="broker.3782",
        command_id=command.command_id, session_id=session.session_id,
        binding_ref=binding.binding_ref, run_id=lease.run_ref,
        tool_request_ref=command.tool_request_ref, sequence=1,
        request_fingerprint=fp, evidence_ref="admission.evidence.3782",
        accepted_at=NOW - timedelta(seconds=15), expires_at=PLUS,
        revision_ref=command.revision_ref, request_id="request.3782",
    )
    pause = ApprovalPause(
        pause_id="pause.3782", run_id=lease.run_ref,
        agent_runtime_id="runtime.3782", tool_id=BROWSER_CONTROL_TOOL_ID,
        invocation_sha256=lease.approval_invocation_sha256(), requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=1, created_at=MINUS, expires_at=PLUS,
        approval_scope=(BROWSER_CONTROL_TOOL_ID,),
    )
    decision = VerifiedApprovalDecision(
        decision_id="decision.3782", pause_id=pause.pause_id,
        outcome=ApprovalOutcome.APPROVED, authority_ref="p01.3782",
        evidence_ref="p01.evidence.3782", decided_at=NOW - timedelta(seconds=30),
    )
    evidence = BrowserControlAuthorityEvidence(
        evidence_ref=decision.evidence_ref, request_fingerprint=fp,
        permission_request=LocalPermissionRequest(
            action_id="action.3782", run_id=lease.run_ref,
            device_id=lease.device_id, capability=lease.capability,
            target_ref=lease.target_ref(),
        ),
        approval_pause=pause, approval_decision=decision,
        local_policy_ref="policy.3782", expires_at=PLUS,
        command_id=command.command_id,
        admission_ref=admission.admission_ref,
        revision_ref=command.revision_ref,
    )
    return AuthenticatedBrowserControlWorkTicket(
        command=command, admission=admission, binding=binding,
        session=session,
        correlation=BrowserControlP01CommandCorrelation(
            command_id=command.command_id, request_id=admission.request_id,
            binding_ref=binding.binding_ref, request_fingerprint=fp, run_ref=lease.run_ref,
        ),
        lease_request=lease, evidence=evidence,
        action=BrowserControlActionRequest(
            action="click", browser_session_ref=lease.browser_session_ref,
            origin_ref=lease.origin_scope, element_ref="el-0001",
        ),
        host_lease_ref="hostlease.3782",
    )


class Test3782BrokerControlWorkTicket(unittest.TestCase):
    def test_exact_distinct_p01_broker_device_action_correlation(self) -> None:
        t = ticket()
        t.validate_at(NOW)
        safe = t.safe_dict()
        self.assertEqual(safe["capability"], "browser.control")
        self.assertFalse(safe["browser_action_executed"])
        self.assertFalse(safe["durable_take_performed"])
        self.assertFalse(BROKER_BROWSER_CONTROL_SOURCE_WIRED)
        self.assertFalse(DESKTOP_ACTION_DELIVERY_WIRED)

    def test_wrong_command_binding_request_run_revision_and_fingerprint_refuse(self) -> None:
        t = ticket()
        mismatches = (
            replace(t, command=replace(t.command, command_id="command.other")),
            replace(t, session=replace(t.session, binding_ref="binding.other")),
            replace(t, correlation=replace(t.correlation, request_id="request.other")),
            replace(t, admission=replace(t.admission, run_id="run.other")),
            replace(t, admission=replace(t.admission, revision_ref="revision.other")),
            replace(t, admission=replace(t.admission, request_fingerprint="a" * 64)),
            replace(t, evidence=replace(t.evidence, command_id=None)),
            replace(t, evidence=replace(t.evidence, admission_ref=None)),
            replace(t, evidence=replace(t.evidence, revision_ref="revision.other")),
            replace(t, admission=replace(t.admission, session_id="session.other")),
            replace(t, binding=replace(t.binding, workspace_ref="workspace.other")),
        )
        for bad in mismatches:
            with self.subTest(bad=bad), self.assertRaises(ContractError):
                bad.validate_at(NOW)

    def test_denied_p01_or_wrong_action_origin_session_and_allowed_classes_refuse(self) -> None:
        t = ticket()
        denied = replace(
            t.evidence,
            approval_decision=replace(t.evidence.approval_decision, outcome=ApprovalOutcome.DENIED),
        )
        bad = (
            replace(t, evidence=denied),
            replace(t, evidence=replace(t.evidence, permission_request=replace(
                t.evidence.permission_request, target_ref="target.other"))),
            replace(t, evidence=replace(t.evidence, approval_pause=replace(
                t.evidence.approval_pause, approval_scope=("process.execute",)))),
            replace(t, action=replace(t.action, origin_ref="https://other.example")),
            replace(t, action=replace(t.action, browser_session_ref="browser.session.other")),
            replace(t, lease_request=replace(t.lease_request, allowed_action_classes=("scroll",))),
        )
        for item in bad:
            with self.assertRaises(ContractError):
                item.validate_at(NOW)

    def test_expired_session_command_approval_and_host_reference_refuse(self) -> None:
        t = ticket()
        for item in (
            replace(t, host_lease_ref="illegal ref"),
            replace(t, host_lease_ref=""),
            replace(t, binding=replace(t.binding, state=DeviceLifecycle.REVOKED)),
            replace(t, command=replace(t.command, expires_at=NOW - timedelta(seconds=1))),
            replace(t, session=replace(t.session, expires_at=NOW - timedelta(seconds=1))),
            replace(t, evidence=replace(t.evidence, expires_at=NOW - timedelta(seconds=1))),
        ):
            with self.assertRaises(ContractError):
                item.validate_at(NOW)
        with self.assertRaises(ContractError):
            t.validate_at(NOW + timedelta(days=1))

    def test_no_raw_approval_or_action_text_crosses_safe_projection(self) -> None:
        t = ticket()
        projection = t.safe_dict()
        self.assertNotIn("action", projection)
        self.assertNotIn("approval_decision", projection)
        self.assertNotIn("credential_ref", projection)
        self.assertNotIn("host_lease_ref", projection)


if __name__ == "__main__":
    unittest.main()
