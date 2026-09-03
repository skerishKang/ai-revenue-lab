from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from padiem_ai_core.agent_approval import (
    ApprovalOutcome,
    ApprovalPause,
    ApprovalRequirement,
    VerifiedApprovalDecision,
    tool_invocation_digest,
)

from kagent.contracts import ContractError
from kagent.local_agent import LocalCommandRequest
from kagent.local_agent_permissions import (
    CapabilityRule,
    DevicePermissionProfile,
    LocalCapability,
    LocalPermissionRequest,
    LocalPolicyMode,
    RootPermissionPolicy,
)
from kagent.windows_execution_authorization import (
    P01LocalPermissionWindowsExecutionAuthorizationPort,
    WINDOWS_EXECUTION_TOOL_ID,
    WindowsExecutableProfile,
    command_request_fingerprint,
    windows_execution_tool_invocation,
)
from kagent.windows_execution_evidence_source import (
    CLIENT_APPROVAL_AUTHORITY,
    EXACT_FINGERPRINT_LOOKUP,
    P01_AUTHORITY_PINNED,
    P01_POLICY_DUPLICATED,
    PRODUCTION_READY,
    RAW_ARGV_IN_EVIDENCE_ENVELOPE,
    RAW_CREDENTIAL_IN_EVIDENCE_ENVELOPE,
    REAL_P01_REMOTE_EVIDENCE_CLIENT_CONFIGURED,
    REAL_REMOTE_BROKER_CONFIGURED,
    TRUSTED_P01_WINDOWS_EVIDENCE_ADAPTER_IMPLEMENTED,
    DeterministicTrustedP01WindowsExecutionEvidenceClient,
    TrustedP01WindowsExecutionAuthorityEvidencePort,
    TrustedP01WindowsExecutionEvidenceEnvelope,
)


class _StaticClient:
    def __init__(self, value: object) -> None:
        self.value = value
        self.calls: list[str] = []

    def resolve(self, request_fingerprint: str):
        self.calls.append(request_fingerprint)
        return self.value


def _fixture(
    *,
    outcome: ApprovalOutcome = ApprovalOutcome.APPROVED,
    authority_ref: str = "p01_authority_prod",
    evidence_ref: str = "p01_evidence_exec_1",
) -> tuple[
    datetime,
    LocalCommandRequest,
    WindowsExecutableProfile,
    DevicePermissionProfile,
    TrustedP01WindowsExecutionEvidenceEnvelope,
]:
    now = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)
    request = LocalCommandRequest(
        request_id="request_exec_1",
        run_id="run_exec_1",
        device_id="device_win_1",
        root_ref="root_code",
        argv=(r"C:\Python311\python.exe", "-V"),
        cwd_relative=".",
        requested_at=now,
        timeout_seconds=30,
    )
    profile = WindowsExecutableProfile(
        profile_ref="python311_profile",
        executable_path=r"C:\Python311\python.exe",
        required_capabilities=(LocalCapability.PROCESS_EXECUTE.value,),
    )
    fingerprint = command_request_fingerprint(request)
    permission_request = LocalPermissionRequest(
        action_id="action_exec_1",
        run_id=request.run_id,
        device_id=request.device_id,
        capability=LocalCapability.PROCESS_EXECUTE,
        target_ref=fingerprint,
        root_ref=request.root_ref,
    )
    pause = ApprovalPause(
        pause_id="pause_exec_1",
        run_id=request.run_id,
        agent_runtime_id="agent_runtime_1",
        tool_id=WINDOWS_EXECUTION_TOOL_ID,
        invocation_sha256=tool_invocation_digest(windows_execution_tool_invocation(request, profile)),
        requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=1,
        created_at=now,
        expires_at=now + timedelta(minutes=10),
        approval_scope=(LocalCapability.PROCESS_EXECUTE.value,),
    )
    decision = VerifiedApprovalDecision(
        decision_id="decision_exec_1",
        pause_id=pause.pause_id,
        outcome=outcome,
        authority_ref=authority_ref,
        evidence_ref=evidence_ref,
        decided_at=now + timedelta(minutes=1),
    )
    envelope = TrustedP01WindowsExecutionEvidenceEnvelope(
        evidence_ref=evidence_ref,
        request_fingerprint=fingerprint,
        approval_pause=pause,
        approval_decision=decision,
        permission_requests=(permission_request,),
        local_policy_ref="local_policy_exec_1",
        expires_at=now + timedelta(minutes=5),
    )
    permission_profile = DevicePermissionProfile(
        device_id=request.device_id,
        workspace_ref="workspace_1",
        roots=(
            RootPermissionPolicy(
                root_ref=request.root_ref,
                rules=(CapabilityRule(LocalCapability.PROCESS_EXECUTE, LocalPolicyMode.ASK),),
            ),
        ),
        global_rules=(),
    )
    return now, request, profile, permission_profile, envelope


class TrustedP01WindowsExecutionEvidenceEnvelopeTests(unittest.TestCase):
    def test_safe_projection_is_bounded_and_contains_no_raw_execution_or_secret_payload(self) -> None:
        _, _, _, _, envelope = _fixture()
        safe = envelope.safe_dict()
        self.assertEqual(safe["contract_version"], "claw-trusted-p01-windows-evidence.v1")
        self.assertFalse(safe["raw_argv"])
        self.assertFalse(safe["raw_credential"])
        self.assertFalse(safe["actor_session_payload"])
        self.assertFalse(safe["approval_ui_payload"])
        self.assertFalse(safe["client_approval_authority"])
        self.assertNotIn("argv", safe)
        self.assertNotIn("credential", safe)
        self.assertNotIn("token", safe)

    def test_rejects_non_windows_tool_pause(self) -> None:
        now, request, _, _, envelope = _fixture()
        bad_pause = ApprovalPause(
            pause_id="pause_other_1",
            run_id=request.run_id,
            agent_runtime_id="agent_runtime_1",
            tool_id="filesystem.read",
            invocation_sha256="0" * 64,
            requirement=ApprovalRequirement.USER_CONFIRMATION,
            step_index=1,
            created_at=now,
            expires_at=now + timedelta(minutes=10),
        )
        bad_decision = VerifiedApprovalDecision(
            decision_id="decision_other_1",
            pause_id=bad_pause.pause_id,
            outcome=ApprovalOutcome.APPROVED,
            authority_ref="p01_authority_prod",
            evidence_ref="p01_evidence_other_1",
            decided_at=now + timedelta(minutes=1),
        )
        with self.assertRaisesRegex(ContractError, "local.process.execute"):
            TrustedP01WindowsExecutionEvidenceEnvelope(
                evidence_ref=bad_decision.evidence_ref,
                request_fingerprint=envelope.request_fingerprint,
                approval_pause=bad_pause,
                approval_decision=bad_decision,
                permission_requests=envelope.permission_requests,
                local_policy_ref="local_policy_exec_1",
                expires_at=now + timedelta(minutes=5),
            )

    def test_rejects_evidence_ref_mismatch(self) -> None:
        now, _, _, _, envelope = _fixture()
        mismatched = VerifiedApprovalDecision(
            decision_id="decision_exec_2",
            pause_id=envelope.approval_pause.pause_id,
            outcome=ApprovalOutcome.APPROVED,
            authority_ref="p01_authority_prod",
            evidence_ref="different_evidence_ref",
            decided_at=now + timedelta(minutes=1),
        )
        with self.assertRaisesRegex(ContractError, "evidence_ref"):
            TrustedP01WindowsExecutionEvidenceEnvelope(
                evidence_ref=envelope.evidence_ref,
                request_fingerprint=envelope.request_fingerprint,
                approval_pause=envelope.approval_pause,
                approval_decision=mismatched,
                permission_requests=envelope.permission_requests,
                local_policy_ref=envelope.local_policy_ref,
                expires_at=envelope.expires_at,
            )

    def test_rejects_permission_run_or_fingerprint_mix(self) -> None:
        _, request, _, _, envelope = _fixture()
        bad_permission = LocalPermissionRequest(
            action_id="action_exec_bad",
            run_id="run_other",
            device_id=request.device_id,
            capability=LocalCapability.PROCESS_EXECUTE,
            target_ref=envelope.request_fingerprint,
            root_ref=request.root_ref,
        )
        with self.assertRaisesRegex(ContractError, "run_id"):
            TrustedP01WindowsExecutionEvidenceEnvelope(
                evidence_ref=envelope.evidence_ref,
                request_fingerprint=envelope.request_fingerprint,
                approval_pause=envelope.approval_pause,
                approval_decision=envelope.approval_decision,
                permission_requests=(bad_permission,),
                local_policy_ref=envelope.local_policy_ref,
                expires_at=envelope.expires_at,
            )

        bad_target = LocalPermissionRequest(
            action_id="action_exec_bad_target",
            run_id=request.run_id,
            device_id=request.device_id,
            capability=LocalCapability.PROCESS_EXECUTE,
            target_ref="f" * 64,
            root_ref=request.root_ref,
        )
        with self.assertRaisesRegex(ContractError, "fingerprint"):
            TrustedP01WindowsExecutionEvidenceEnvelope(
                evidence_ref=envelope.evidence_ref,
                request_fingerprint=envelope.request_fingerprint,
                approval_pause=envelope.approval_pause,
                approval_decision=envelope.approval_decision,
                permission_requests=(bad_target,),
                local_policy_ref=envelope.local_policy_ref,
                expires_at=envelope.expires_at,
            )

    def test_evidence_lease_cannot_outlive_pause(self) -> None:
        now, _, _, _, envelope = _fixture()
        with self.assertRaisesRegex(ContractError, "outlive"):
            TrustedP01WindowsExecutionEvidenceEnvelope(
                evidence_ref=envelope.evidence_ref,
                request_fingerprint=envelope.request_fingerprint,
                approval_pause=envelope.approval_pause,
                approval_decision=envelope.approval_decision,
                permission_requests=envelope.permission_requests,
                local_policy_ref=envelope.local_policy_ref,
                expires_at=now + timedelta(minutes=11),
            )


class TrustedP01WindowsExecutionAuthorityEvidencePortTests(unittest.TestCase):
    def test_exact_fingerprint_lookup_and_authority_pin(self) -> None:
        _, _, _, _, envelope = _fixture()
        client = DeterministicTrustedP01WindowsExecutionEvidenceClient((envelope,))
        port = TrustedP01WindowsExecutionAuthorityEvidencePort(
            expected_authority_ref="p01_authority_prod",
            client=client,
        )
        resolved = port.resolve(envelope.request_fingerprint)
        self.assertEqual(resolved.evidence_ref, envelope.evidence_ref)
        self.assertEqual(resolved.request_fingerprint, envelope.request_fingerprint)
        self.assertEqual(client.calls, [envelope.request_fingerprint])

    def test_unknown_fingerprint_fails_closed(self) -> None:
        _, _, _, _, envelope = _fixture()
        client = DeterministicTrustedP01WindowsExecutionEvidenceClient((envelope,))
        port = TrustedP01WindowsExecutionAuthorityEvidencePort(
            expected_authority_ref="p01_authority_prod",
            client=client,
        )
        with self.assertRaisesRegex(ContractError, "does not exist"):
            port.resolve("a" * 64)

    def test_client_returning_different_fingerprint_fails_closed(self) -> None:
        _, _, _, _, envelope = _fixture()
        port = TrustedP01WindowsExecutionAuthorityEvidencePort(
            expected_authority_ref="p01_authority_prod",
            client=_StaticClient(envelope),
        )
        with self.assertRaisesRegex(ContractError, "fingerprint mismatch"):
            port.resolve("b" * 64)

    def test_wrong_p01_authority_fails_closed(self) -> None:
        _, _, _, _, envelope = _fixture(authority_ref="p01_authority_other")
        port = TrustedP01WindowsExecutionAuthorityEvidencePort(
            expected_authority_ref="p01_authority_prod",
            client=DeterministicTrustedP01WindowsExecutionEvidenceClient((envelope,)),
        )
        with self.assertRaisesRegex(ContractError, "authority mismatch"):
            port.resolve(envelope.request_fingerprint)

    def test_unconfigured_remote_client_fails_closed(self) -> None:
        _, _, _, _, envelope = _fixture()
        port = TrustedP01WindowsExecutionAuthorityEvidencePort(
            expected_authority_ref="p01_authority_prod",
        )
        with self.assertRaisesRegex(ContractError, "not configured"):
            port.resolve(envelope.request_fingerprint)

    def test_invalid_client_return_type_fails_closed(self) -> None:
        _, _, _, _, envelope = _fixture()
        port = TrustedP01WindowsExecutionAuthorityEvidencePort(
            expected_authority_ref="p01_authority_prod",
            client=_StaticClient(object()),
        )
        with self.assertRaisesRegex(ContractError, "invalid envelope"):
            port.resolve(envelope.request_fingerprint)


class ExistingWindowsAuthorizationIntegrationTests(unittest.TestCase):
    def test_trusted_evidence_adapter_feeds_existing_p01_local_authorization(self) -> None:
        now, request, profile, permission_profile, envelope = _fixture()
        evidence_port = TrustedP01WindowsExecutionAuthorityEvidencePort(
            expected_authority_ref="p01_authority_prod",
            client=DeterministicTrustedP01WindowsExecutionEvidenceClient((envelope,)),
        )
        authorization = P01LocalPermissionWindowsExecutionAuthorizationPort(
            permission_profile=permission_profile,
            evidence_port=evidence_port,
        )
        grant = authorization.authorize(
            request=request,
            profile=profile,
            now=now + timedelta(minutes=2),
        )
        self.assertEqual(grant.request_fingerprint, envelope.request_fingerprint)
        self.assertEqual(grant.p01_approval_ref, envelope.approval_decision.decision_id)
        self.assertEqual(grant.local_policy_ref, envelope.local_policy_ref)
        with self.assertRaisesRegex(ContractError, "already been consumed"):
            authorization.authorize(
                request=request,
                profile=profile,
                now=now + timedelta(minutes=2),
            )

    def test_denied_p01_decision_is_not_promoted_by_evidence_adapter(self) -> None:
        now, request, profile, permission_profile, envelope = _fixture(outcome=ApprovalOutcome.DENIED)
        evidence_port = TrustedP01WindowsExecutionAuthorityEvidencePort(
            expected_authority_ref="p01_authority_prod",
            client=DeterministicTrustedP01WindowsExecutionEvidenceClient((envelope,)),
        )
        authorization = P01LocalPermissionWindowsExecutionAuthorizationPort(
            permission_profile=permission_profile,
            evidence_port=evidence_port,
        )
        with self.assertRaisesRegex(ContractError, "approved canonical P01 decision"):
            authorization.authorize(
                request=request,
                profile=profile,
                now=now + timedelta(minutes=2),
            )

    def test_contract_flags_make_non_claims_explicit(self) -> None:
        self.assertTrue(TRUSTED_P01_WINDOWS_EVIDENCE_ADAPTER_IMPLEMENTED)
        self.assertTrue(P01_AUTHORITY_PINNED)
        self.assertTrue(EXACT_FINGERPRINT_LOOKUP)
        self.assertFalse(CLIENT_APPROVAL_AUTHORITY)
        self.assertFalse(P01_POLICY_DUPLICATED)
        self.assertFalse(RAW_ARGV_IN_EVIDENCE_ENVELOPE)
        self.assertFalse(RAW_CREDENTIAL_IN_EVIDENCE_ENVELOPE)
        self.assertFalse(REAL_P01_REMOTE_EVIDENCE_CLIENT_CONFIGURED)
        self.assertFalse(REAL_REMOTE_BROKER_CONFIGURED)
        self.assertFalse(PRODUCTION_READY)


if __name__ == "__main__":
    unittest.main()
