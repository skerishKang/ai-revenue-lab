from __future__ import annotations

import unittest

from kagent.contracts import ContractError
from kagent.local_agent import LocalAgentDeviceProfile, LocalAgentPlatform, LocalRoot
from kagent.local_agent_permissions import (
    ADMIN_ELEVATION_DEFAULT_ALLOWED,
    BROWSER_CONTROL_IMPLIED_BY_FILESYSTEM,
    GIT_PUSH_DEFAULT_ENABLED,
    LOCAL_AGENT_CAN_WEAKEN_P01_POLICY,
    LOCAL_AGENT_MAY_FAIL_CLOSED,
    NETWORK_DEFAULT_ENABLED,
    P01_APPROVAL_AUTHORITY_DUPLICATED,
    UNBOUNDED_SECRET_ENV_INHERITANCE,
    WHOLE_PC_GRANT_SUPPORTED,
    CapabilityRule,
    DevicePermissionProfile,
    LocalCapability,
    LocalEnforcementResult,
    LocalPermissionRequest,
    LocalPolicyMode,
    RootPermissionPolicy,
    default_device_permission_profile,
    evaluate_local_permission,
    revoke_root,
)


def device() -> LocalAgentDeviceProfile:
    return LocalAgentDeviceProfile(
        device_id="device_local_1",
        workspace_ref="workspace_1",
        platform=LocalAgentPlatform.WINDOWS,
        roots=(
            LocalRoot(root_ref="repo", windows_path=r"E:\workspace\repo"),
            LocalRoot(root_ref="docs", windows_path=r"D:\Documents\Padiem"),
        ),
    )


def request(capability: LocalCapability, *, root_ref: str | None = None, **kwargs) -> LocalPermissionRequest:
    values = dict(
        action_id="action_1",
        run_id="run_1",
        device_id="device_local_1",
        capability=capability,
        target_ref="target_1",
        root_ref=root_ref,
    )
    values.update(kwargs)
    return LocalPermissionRequest(**values)


class LocalAgentPermissionTests(unittest.TestCase):
    def test_capability_vocabulary_is_explicit_and_non_collapsed(self):
        self.assertEqual(
            {capability.value for capability in LocalCapability},
            {
                "filesystem.read",
                "filesystem.write",
                "filesystem.delete",
                "process.execute",
                "git.read",
                "git.write_local",
                "git.commit",
                "git.network",
                "browser.open",
                "browser.control",
                "clipboard.read",
                "clipboard.write",
                "network.outbound",
                "admin.elevation",
            },
        )
        self.assertEqual(len(LocalCapability), 14)

    def test_default_root_policy_allows_read_asks_for_mutation_and_denies_git_network(self):
        profile = default_device_permission_profile(device=device())
        repo = profile.root_policy("repo")
        self.assertEqual(repo.mode_for(LocalCapability.FILESYSTEM_READ), LocalPolicyMode.ALLOW)
        self.assertEqual(repo.mode_for(LocalCapability.GIT_READ), LocalPolicyMode.ALLOW)
        self.assertEqual(repo.mode_for(LocalCapability.FILESYSTEM_WRITE), LocalPolicyMode.ASK)
        self.assertEqual(repo.mode_for(LocalCapability.FILESYSTEM_DELETE), LocalPolicyMode.ASK)
        self.assertEqual(repo.mode_for(LocalCapability.PROCESS_EXECUTE), LocalPolicyMode.ASK)
        self.assertEqual(repo.mode_for(LocalCapability.GIT_WRITE_LOCAL), LocalPolicyMode.ASK)
        self.assertEqual(repo.mode_for(LocalCapability.GIT_COMMIT), LocalPolicyMode.ASK)
        self.assertEqual(repo.mode_for(LocalCapability.GIT_NETWORK), LocalPolicyMode.DENY)

    def test_default_global_policy_asks_for_browser_clipboard_and_denies_network_admin(self):
        profile = default_device_permission_profile(device=device())
        self.assertEqual(profile.global_mode(LocalCapability.BROWSER_OPEN), LocalPolicyMode.ASK)
        self.assertEqual(profile.global_mode(LocalCapability.BROWSER_CONTROL), LocalPolicyMode.ASK)
        self.assertEqual(profile.global_mode(LocalCapability.CLIPBOARD_READ), LocalPolicyMode.ASK)
        self.assertEqual(profile.global_mode(LocalCapability.CLIPBOARD_WRITE), LocalPolicyMode.ASK)
        self.assertEqual(profile.global_mode(LocalCapability.NETWORK_OUTBOUND), LocalPolicyMode.DENY)
        self.assertEqual(profile.global_mode(LocalCapability.ADMIN_ELEVATION), LocalPolicyMode.DENY)

    def test_read_is_locally_allowed_but_write_delete_and_process_require_p01_approval(self):
        profile = default_device_permission_profile(device=device())
        read = evaluate_local_permission(
            profile=profile,
            request=request(LocalCapability.FILESYSTEM_READ, root_ref="repo"),
        )
        self.assertEqual(read.result, LocalEnforcementResult.LOCALLY_ALLOWED)
        self.assertFalse(read.p01_approval_required)

        for capability in (
            LocalCapability.FILESYSTEM_WRITE,
            LocalCapability.FILESYSTEM_DELETE,
            LocalCapability.PROCESS_EXECUTE,
        ):
            decision = evaluate_local_permission(
                profile=profile,
                request=request(capability, root_ref="repo"),
            )
            self.assertEqual(decision.result, LocalEnforcementResult.REQUIRE_P01_APPROVAL)
            self.assertTrue(decision.p01_approval_required)
            self.assertTrue(decision.local_policy_may_only_narrow)

    def test_network_git_network_and_admin_are_denied_without_minting_approval(self):
        profile = default_device_permission_profile(device=device())
        cases = (
            request(LocalCapability.GIT_NETWORK, root_ref="repo"),
            request(LocalCapability.NETWORK_OUTBOUND),
            request(LocalCapability.ADMIN_ELEVATION),
        )
        for permission_request in cases:
            decision = evaluate_local_permission(profile=profile, request=permission_request)
            self.assertEqual(decision.result, LocalEnforcementResult.DENIED)
            self.assertFalse(decision.p01_approval_required)

    def test_browser_control_is_distinct_from_filesystem_access(self):
        profile = default_device_permission_profile(device=device())
        filesystem = evaluate_local_permission(
            profile=profile,
            request=request(LocalCapability.FILESYSTEM_READ, root_ref="repo"),
        )
        browser = evaluate_local_permission(
            profile=profile,
            request=request(LocalCapability.BROWSER_CONTROL),
        )
        self.assertEqual(filesystem.result, LocalEnforcementResult.LOCALLY_ALLOWED)
        self.assertEqual(browser.result, LocalEnforcementResult.REQUIRE_P01_APPROVAL)
        self.assertFalse(BROWSER_CONTROL_IMPLIED_BY_FILESYSTEM)

    def test_root_scoped_capabilities_require_root_and_global_capabilities_reject_root(self):
        with self.assertRaises(ContractError):
            request(LocalCapability.FILESYSTEM_READ)
        with self.assertRaises(ContractError):
            request(LocalCapability.NETWORK_OUTBOUND, root_ref="repo")

    def test_device_mismatch_and_unknown_root_fail_closed(self):
        profile = default_device_permission_profile(device=device())
        with self.assertRaises(ContractError):
            evaluate_local_permission(
                profile=profile,
                request=request(
                    LocalCapability.FILESYSTEM_READ,
                    root_ref="repo",
                    device_id="device_other",
                ),
            )
        with self.assertRaises(ContractError):
            evaluate_local_permission(
                profile=profile,
                request=request(LocalCapability.FILESYSTEM_READ, root_ref="missing"),
            )

    def test_missing_rule_is_deny_not_implicit_allow(self):
        profile = DevicePermissionProfile(
            device_id="device_local_1",
            workspace_ref="workspace_1",
            roots=(
                RootPermissionPolicy(
                    root_ref="repo",
                    rules=(CapabilityRule(LocalCapability.FILESYSTEM_READ, LocalPolicyMode.ALLOW),),
                ),
            ),
            global_rules=(),
        )
        write = evaluate_local_permission(
            profile=profile,
            request=request(LocalCapability.FILESYSTEM_WRITE, root_ref="repo"),
        )
        network = evaluate_local_permission(
            profile=profile,
            request=request(LocalCapability.NETWORK_OUTBOUND),
        )
        self.assertEqual(write.result, LocalEnforcementResult.DENIED)
        self.assertEqual(network.result, LocalEnforcementResult.DENIED)

    def test_revoked_root_stops_subsequent_access(self):
        profile = default_device_permission_profile(device=device())
        narrowed = revoke_root(profile, root_ref="docs")
        self.assertEqual([root.root_ref for root in narrowed.roots], ["repo"])
        with self.assertRaises(ContractError):
            evaluate_local_permission(
                profile=narrowed,
                request=request(LocalCapability.FILESYSTEM_READ, root_ref="docs"),
            )
        with self.assertRaises(ContractError):
            revoke_root(narrowed, root_ref="repo")

    def test_safe_projection_never_claims_whole_pc_or_client_approval_authority(self):
        profile = default_device_permission_profile(device=device())
        self.assertFalse(profile.safe_dict()["whole_pc_grant"])
        self.assertFalse(profile.safe_dict()["p01_authority_duplicated"])
        self.assertFalse(
            request(LocalCapability.FILESYSTEM_WRITE, root_ref="repo").safe_dict()[
                "client_approval_authority"
            ]
        )

    def test_local_policy_is_only_a_narrowing_gate_not_a_second_p01_approval_engine(self):
        profile = default_device_permission_profile(device=device())
        decision = evaluate_local_permission(
            profile=profile,
            request=request(LocalCapability.GIT_COMMIT, root_ref="repo"),
        )
        self.assertEqual(decision.result, LocalEnforcementResult.REQUIRE_P01_APPROVAL)
        self.assertTrue(decision.p01_approval_required)
        self.assertTrue(decision.local_policy_may_only_narrow)
        self.assertFalse(P01_APPROVAL_AUTHORITY_DUPLICATED)
        self.assertFalse(LOCAL_AGENT_CAN_WEAKEN_P01_POLICY)
        self.assertTrue(LOCAL_AGENT_MAY_FAIL_CLOSED)

    def test_security_defaults_remain_fail_closed(self):
        self.assertFalse(WHOLE_PC_GRANT_SUPPORTED)
        self.assertFalse(NETWORK_DEFAULT_ENABLED)
        self.assertFalse(GIT_PUSH_DEFAULT_ENABLED)
        self.assertFalse(ADMIN_ELEVATION_DEFAULT_ALLOWED)
        self.assertFalse(UNBOUNDED_SECRET_ENV_INHERITANCE)


if __name__ == "__main__":
    unittest.main()
