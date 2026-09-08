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
from kagent.local_agent import LocalAgentDeviceProfile, LocalAgentPlatform, LocalCommandRequest, LocalRoot
from kagent.local_agent_permissions import (
    CapabilityRule,
    DevicePermissionProfile,
    LocalCapability,
    LocalPermissionRequest,
    LocalPolicyMode,
    default_device_permission_profile,
)
from kagent.windows_execution_authorization import (
    CLIENT_PERMISSION_DECISION_AUTHORITY,
    LOCAL_POLICY_MAY_WIDEN_P01,
    P01_APPROVAL_AUTHORITY_DUPLICATED,
    PRODUCTION_REMOTE_CONTROL_CLAIMED,
    REAL_WINDOWS_P01_PERMISSION_AUTHORIZATION_ADAPTER_IMPLEMENTED,
    DeterministicWindowsExecutionAuthorityEvidencePort,
    P01LocalPermissionWindowsExecutionAuthorizationPort,
    WindowsExecutionAuthorityEvidence,
    windows_execution_tool_invocation,
)
from kagent.windows_local_executor import WindowsExecutableProfile, command_request_fingerprint

NOW = datetime(2026, 9, 3, 7, 0, tzinfo=timezone.utc)


def device() -> LocalAgentDeviceProfile:
    return LocalAgentDeviceProfile(
        device_id="device_1",
        workspace_ref="workspace_1",
        platform=LocalAgentPlatform.WINDOWS,
        roots=(LocalRoot(root_ref="repo", windows_path=r"C:\workspace\repo"),),
    )


def permission_profile(*, network_mode: LocalPolicyMode = LocalPolicyMode.DENY) -> DevicePermissionProfile:
    base = default_device_permission_profile(device=device())
    global_rules = tuple(
        CapabilityRule(
            rule.capability,
            network_mode if rule.capability is LocalCapability.NETWORK_OUTBOUND else rule.mode,
        )
        for rule in base.global_rules
    )
    return DevicePermissionProfile(
        device_id=base.device_id,
        workspace_ref=base.workspace_ref,
        roots=base.roots,
        global_rules=global_rules,
    )


def command(*, argv: tuple[str, ...] | None = None) -> LocalCommandRequest:
    return LocalCommandRequest(
        request_id="request_1",
        run_id="run_1",
        device_id="device_1",
        root_ref="repo",
        argv=argv or (r"C:\Python\python.exe", "-m", "pytest"),
        cwd_relative="tests",
        requested_at=NOW - timedelta(minutes=1),
        timeout_seconds=120,
    )


def executable_profile(*, network: bool = False) -> WindowsExecutableProfile:
    capabilities = ("process.execute", "network.outbound") if network else ("process.execute",)
    return WindowsExecutableProfile(
        profile_ref="python",
        executable_path=r"C:\Python\python.exe",
        required_capabilities=capabilities,
        may_access_network=network,
    )


def permission_requests(request: LocalCommandRequest, profile: WindowsExecutableProfile) -> tuple[LocalPermissionRequest, ...]:
    fingerprint = command_request_fingerprint(request)
    result = [
        LocalPermissionRequest(
            action_id="permission_process",
            run_id=request.run_id,
            device_id=request.device_id,
            capability=LocalCapability.PROCESS_EXECUTE,
            target_ref=fingerprint,
            root_ref=request.root_ref,
        )
    ]
    if "network.outbound" in profile.required_capabilities:
        result.append(
            LocalPermissionRequest(
                action_id="permission_network",
                run_id=request.run_id,
                device_id=request.device_id,
                capability=LocalCapability.NETWORK_OUTBOUND,
                target_ref=fingerprint,
                root_ref=None,
            )
        )
    return tuple(result)


def approval_pause(
    request: LocalCommandRequest,
    profile: WindowsExecutableProfile,
    *,
    scope: tuple[str, ...] | None = None,
    expires_at: datetime | None = None,
) -> ApprovalPause:
    invocation = windows_execution_tool_invocation(request, profile)
    return ApprovalPause(
        pause_id="pause_1",
        run_id=request.run_id,
        agent_runtime_id="agent_1",
        tool_id=invocation.tool_id,
        invocation_sha256=tool_invocation_digest(invocation),
        requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=1,
        created_at=NOW - timedelta(minutes=2),
        expires_at=expires_at or NOW + timedelta(minutes=10),
        approval_scope=scope if scope is not None else profile.required_capabilities,
    )


def approval_decision(
    *,
    outcome: ApprovalOutcome = ApprovalOutcome.APPROVED,
    decided_at: datetime | None = None,
) -> VerifiedApprovalDecision:
    return VerifiedApprovalDecision(
        decision_id="decision_1",
        pause_id="pause_1",
        outcome=outcome,
        authority_ref="p01_authority_1",
        evidence_ref="p01_evidence_1",
        decided_at=decided_at or NOW - timedelta(seconds=30),
    )


def evidence(
    request: LocalCommandRequest,
    profile: WindowsExecutableProfile,
    *,
    requests: tuple[LocalPermissionRequest, ...] | None = None,
    pause: ApprovalPause | None = None,
    decision: VerifiedApprovalDecision | None = None,
    expires_at: datetime | None = None,
) -> WindowsExecutionAuthorityEvidence:
    return WindowsExecutionAuthorityEvidence(
        evidence_ref="authority_evidence_1",
        request_fingerprint=command_request_fingerprint(request),
        permission_requests=requests if requests is not None else permission_requests(request, profile),
        approval_pause=pause if pause is not None else approval_pause(request, profile),
        approval_decision=decision if decision is not None else approval_decision(),
        local_policy_ref="local_policy_v1",
        expires_at=expires_at or NOW + timedelta(minutes=5),
    )


def adapter(
    authority: WindowsExecutionAuthorityEvidence,
    *,
    permissions: DevicePermissionProfile | None = None,
) -> P01LocalPermissionWindowsExecutionAuthorizationPort:
    return P01LocalPermissionWindowsExecutionAuthorizationPort(
        permission_profile=permissions or permission_profile(),
        evidence_port=DeterministicWindowsExecutionAuthorityEvidencePort((authority,)),
    )


class WindowsExecutionAuthorizationTests(unittest.TestCase):
    def test_exact_command_receives_grant_from_p01_and_recomputed_local_policy(self):
        request = command()
        profile = executable_profile()
        authority = evidence(request, profile)
        grant = adapter(authority).authorize(request=request, profile=profile, now=NOW)
        self.assertEqual(grant.request_fingerprint, command_request_fingerprint(request))
        self.assertEqual(grant.device_id, request.device_id)
        self.assertEqual(grant.root_ref, request.root_ref)
        self.assertEqual(grant.executable_profile_ref, profile.profile_ref)
        self.assertEqual(grant.capability_refs, ("process.execute",))
        self.assertEqual(grant.p01_approval_ref, "decision_1")
        self.assertEqual(grant.local_policy_ref, "local_policy_v1")
        grant.validate(request=request, profile=profile, now=NOW)
        rendered = authority.safe_dict()
        self.assertFalse(rendered["client_permission_decision_authority"])
        self.assertFalse(rendered["raw_argv"])
        self.assertFalse(rendered["raw_credentials"])

    def test_permission_target_and_process_root_must_match_exact_command(self):
        request = command()
        profile = executable_profile()
        wrong_target = LocalPermissionRequest(
            action_id="permission_process",
            run_id=request.run_id,
            device_id=request.device_id,
            capability=LocalCapability.PROCESS_EXECUTE,
            target_ref="0" * 64,
            root_ref=request.root_ref,
        )
        with self.assertRaises(ContractError):
            adapter(evidence(request, profile, requests=(wrong_target,))).authorize(
                request=request,
                profile=profile,
                now=NOW,
            )
        wrong_root = LocalPermissionRequest(
            action_id="permission_process",
            run_id=request.run_id,
            device_id=request.device_id,
            capability=LocalCapability.PROCESS_EXECUTE,
            target_ref=command_request_fingerprint(request),
            root_ref="other_root",
        )
        with self.assertRaises(ContractError):
            adapter(evidence(request, profile, requests=(wrong_root,))).authorize(
                request=request,
                profile=profile,
                now=NOW,
            )

    def test_network_capability_is_separate_and_local_deny_wins(self):
        request = command()
        profile = executable_profile(network=True)
        authority = evidence(request, profile)
        with self.assertRaisesRegex(ContractError, "local policy denied network.outbound"):
            adapter(authority).authorize(request=request, profile=profile, now=NOW)

        allowed = adapter(
            authority,
            permissions=permission_profile(network_mode=LocalPolicyMode.ALLOW),
        ).authorize(request=request, profile=profile, now=NOW)
        self.assertEqual(set(allowed.capability_refs), {"process.execute", "network.outbound"})

    def test_missing_network_permission_evidence_fails_closed(self):
        request = command()
        profile = executable_profile(network=True)
        process_only = permission_requests(request, executable_profile())
        authority = evidence(request, profile, requests=process_only)
        with self.assertRaisesRegex(ContractError, "exactly cover executable capabilities"):
            adapter(
                authority,
                permissions=permission_profile(network_mode=LocalPolicyMode.ALLOW),
            ).authorize(request=request, profile=profile, now=NOW)

    def test_p01_pause_must_bind_exact_local_command_invocation(self):
        request = command()
        profile = executable_profile()
        altered = command(argv=(r"C:\Python\python.exe", "-m", "unittest"))
        authority = evidence(request, profile, pause=approval_pause(altered, profile))
        with self.assertRaisesRegex(ContractError, "exact local command invocation"):
            adapter(authority).authorize(request=request, profile=profile, now=NOW)

    def test_p01_denial_and_expiry_fail_closed(self):
        request = command()
        profile = executable_profile()
        denied = evidence(
            request,
            profile,
            decision=approval_decision(outcome=ApprovalOutcome.DENIED),
        )
        with self.assertRaisesRegex(ContractError, "approved canonical P01 decision"):
            adapter(denied).authorize(request=request, profile=profile, now=NOW)

        expired_pause = approval_pause(
            request,
            profile,
            expires_at=NOW - timedelta(seconds=1),
        )
        expired = evidence(
            request,
            profile,
            pause=expired_pause,
            decision=approval_decision(decided_at=NOW - timedelta(minutes=1)),
        )
        with self.assertRaisesRegex(ContractError, "denied or expired"):
            adapter(expired).authorize(request=request, profile=profile, now=NOW)

    def test_p01_approval_scope_must_cover_all_required_capabilities(self):
        request = command()
        profile = executable_profile(network=True)
        authority = evidence(
            request,
            profile,
            pause=approval_pause(request, profile, scope=("process.execute",)),
        )
        with self.assertRaisesRegex(ContractError, "scope"):
            adapter(
                authority,
                permissions=permission_profile(network_mode=LocalPolicyMode.ALLOW),
            ).authorize(request=request, profile=profile, now=NOW)

    def test_authorization_evidence_and_p01_decision_are_one_shot(self):
        request = command()
        profile = executable_profile()
        authorization = adapter(evidence(request, profile))
        authorization.authorize(request=request, profile=profile, now=NOW)
        with self.assertRaisesRegex(ContractError, "already been consumed"):
            authorization.authorize(request=request, profile=profile, now=NOW)

    def test_unconfigured_evidence_port_fails_closed(self):
        request = command()
        profile = executable_profile()
        authorization = P01LocalPermissionWindowsExecutionAuthorizationPort(
            permission_profile=permission_profile(),
        )
        with self.assertRaisesRegex(ContractError, "not configured"):
            authorization.authorize(request=request, profile=profile, now=NOW)

    def test_boundary_nonclaims_are_explicit(self):
        self.assertTrue(REAL_WINDOWS_P01_PERMISSION_AUTHORIZATION_ADAPTER_IMPLEMENTED)
        self.assertFalse(CLIENT_PERMISSION_DECISION_AUTHORITY)
        self.assertFalse(P01_APPROVAL_AUTHORITY_DUPLICATED)
        self.assertFalse(LOCAL_POLICY_MAY_WIDEN_P01)
        self.assertFalse(PRODUCTION_REMOTE_CONTROL_CLAIMED)


if __name__ == "__main__":
    unittest.main()
