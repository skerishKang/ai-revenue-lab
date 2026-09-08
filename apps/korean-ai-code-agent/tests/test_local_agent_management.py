from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest

from kagent.contracts import ContractError
from kagent.local_agent import LocalAgentDeviceProfile, LocalAgentPlatform, LocalRoot
from kagent.local_agent_management import (
    ALLOWED_ROOTS_VISIBLE,
    CAPABILITY_POLICY_VISIBLE,
    CLIENT_MANAGEMENT_MUTATION_AUTHORITY,
    DEVICE_STATUS_VISIBLE,
    PRODUCTION_REMOTE_CONTROL_CLAIMED,
    RAW_COMMAND_OUTPUT_VISIBLE,
    RAW_DEVICE_CREDENTIAL_VISIBLE,
    RECENT_ACTIVITY_BOUNDED,
    WORKTREE_PROBE_REQUIRED_FOR_REAL_RUNTIME,
    LocalAgentActivitySummary,
    LocalAgentManagementSnapshot,
    TrustedLocalAgentManagementAuthority,
    compose_fail_closed_windows_runtime,
    rename_device,
    revoke_device,
    revoke_selected_root,
    set_capability_policy,
)
from kagent.local_agent_pairing import DeviceBinding, DeviceLifecycle
from kagent.local_agent_permissions import (
    LocalCapability,
    LocalPolicyMode,
    default_device_permission_profile,
)
from kagent.windows_local_executor import (
    DeterministicFakeWindowsExecutionAuthorizationPort,
    DeterministicWorktreeStatePort,
    WindowsExecutableProfile,
)

NOW = datetime(2026, 9, 3, 7, 15, tzinfo=timezone.utc)


def device() -> LocalAgentDeviceProfile:
    return LocalAgentDeviceProfile(
        device_id="device_1",
        workspace_ref="workspace_1",
        platform=LocalAgentPlatform.WINDOWS,
        roots=(
            LocalRoot(root_ref="repo", windows_path=r"C:\workspace\repo"),
            LocalRoot(root_ref="docs", windows_path=r"D:\Padiem\docs"),
        ),
    )


def binding(*, state: DeviceLifecycle = DeviceLifecycle.ONLINE) -> DeviceBinding:
    return DeviceBinding(
        device_id="device_1",
        binding_ref="binding_1",
        account_ref="account_1",
        workspace_ref="workspace_1",
        credential_ref="opaque_credential_ref",
        credential_generation=2,
        issued_at=NOW - timedelta(hours=1),
        credential_expires_at=NOW + timedelta(days=7),
        state=state,
    )


def authority(**kwargs) -> TrustedLocalAgentManagementAuthority:
    values = dict(
        authority_ref="management_authority_1",
        actor_ref="actor_1",
        workspace_ref="workspace_1",
        device_id="device_1",
        issued_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(minutes=30),
    )
    values.update(kwargs)
    return TrustedLocalAgentManagementAuthority(**values)


def activity(index: int = 1) -> LocalAgentActivitySummary:
    return LocalAgentActivitySummary(
        request_id=f"request_{index}",
        run_id=f"run_{index}",
        root_ref="repo",
        executable_profile_ref="python",
        termination="exited",
        started_at=NOW - timedelta(seconds=2),
        ended_at=NOW - timedelta(seconds=1),
        exit_code=0,
        dirty_worktree_before=True,
        dirty_worktree_after=True,
    )


class RecordingRevocationPort:
    def __init__(self, original: DeviceBinding) -> None:
        self.original = original
        self.calls: list[str] = []

    def revoke(self, binding_ref: str, *, now: datetime) -> DeviceBinding:
        self.calls.append(binding_ref)
        return replace(self.original, state=DeviceLifecycle.REVOKED)


class LocalAgentManagementTests(unittest.TestCase):
    def test_snapshot_exposes_status_roots_policies_and_bounded_activity_without_authority_or_raw_output(self):
        local_device = device()
        snapshot = LocalAgentManagementSnapshot(
            device_name="Office PC",
            device=local_device,
            binding=binding(),
            permissions=default_device_permission_profile(device=local_device),
            recent_activity=(activity(),),
        )
        rendered = snapshot.safe_dict()
        self.assertEqual(rendered["device_name"], "Office PC")
        self.assertEqual(rendered["status"], "online")
        self.assertEqual({item["root_ref"] for item in rendered["roots"]}, {"repo", "docs"})
        self.assertTrue(all("windows_path" in item for item in rendered["roots"]))
        self.assertTrue(rendered["recent_activity"])
        self.assertFalse(rendered["raw_device_credential"])
        self.assertFalse(rendered["raw_command_output"])
        self.assertFalse(rendered["execution_authority"])
        self.assertFalse(rendered["client_mutation_authority"])
        activity_rendered = rendered["recent_activity"][0]
        self.assertFalse(activity_rendered["raw_argv"])
        self.assertFalse(activity_rendered["stdout"])
        self.assertFalse(activity_rendered["stderr"])

    def test_recent_activity_is_bounded(self):
        local_device = device()
        with self.assertRaises(ContractError):
            LocalAgentManagementSnapshot(
                device_name="Office PC",
                device=local_device,
                binding=binding(),
                permissions=default_device_permission_profile(device=local_device),
                recent_activity=tuple(activity(i) for i in range(1, 22)),
            )

    def test_exact_root_capability_policy_change_does_not_widen_unrelated_rules(self):
        permissions = default_device_permission_profile(device=device())
        before_docs = permissions.root_policy("docs")
        updated, receipt = set_capability_policy(
            permissions=permissions,
            authority=authority(),
            capability=LocalCapability.PROCESS_EXECUTE,
            mode=LocalPolicyMode.DENY,
            root_ref="repo",
            operation_ref="operation_1",
            now=NOW,
        )
        self.assertEqual(updated.root_policy("repo").mode_for(LocalCapability.PROCESS_EXECUTE), LocalPolicyMode.DENY)
        self.assertEqual(updated.root_policy("repo").mode_for(LocalCapability.FILESYSTEM_READ), LocalPolicyMode.ALLOW)
        self.assertEqual(updated.root_policy("docs"), before_docs)
        self.assertEqual(receipt.operation, "set_capability_policy")
        self.assertEqual(receipt.target_ref, "root:repo:process.execute")

    def test_global_network_policy_is_separate_and_admin_cannot_be_enabled(self):
        permissions = default_device_permission_profile(device=device())
        updated, _ = set_capability_policy(
            permissions=permissions,
            authority=authority(),
            capability=LocalCapability.NETWORK_OUTBOUND,
            mode=LocalPolicyMode.ASK,
            operation_ref="operation_network",
            now=NOW,
        )
        self.assertEqual(updated.global_mode(LocalCapability.NETWORK_OUTBOUND), LocalPolicyMode.ASK)
        self.assertEqual(updated.global_mode(LocalCapability.ADMIN_ELEVATION), LocalPolicyMode.DENY)
        with self.assertRaises(ContractError):
            set_capability_policy(
                permissions=permissions,
                authority=authority(),
                capability=LocalCapability.ADMIN_ELEVATION,
                mode=LocalPolicyMode.ALLOW,
                operation_ref="operation_admin",
                now=NOW,
            )

    def test_management_authority_mismatch_or_expiry_fails_closed(self):
        permissions = default_device_permission_profile(device=device())
        with self.assertRaises(ContractError):
            set_capability_policy(
                permissions=permissions,
                authority=authority(device_id="device_other"),
                capability=LocalCapability.PROCESS_EXECUTE,
                mode=LocalPolicyMode.DENY,
                root_ref="repo",
                operation_ref="operation_bad_device",
                now=NOW,
            )
        with self.assertRaises(ContractError):
            rename_device(
                current_name="Office PC",
                new_name="Renamed PC",
                authority=authority(expires_at=NOW - timedelta(seconds=1)),
                device=device(),
                operation_ref="operation_expired",
                now=NOW,
            )

    def test_device_rename_is_label_only_and_authority_bound(self):
        new_name, receipt = rename_device(
            current_name="Office PC",
            new_name="Build Workstation",
            authority=authority(),
            device=device(),
            operation_ref="operation_rename",
            now=NOW,
        )
        self.assertEqual(new_name, "Build Workstation")
        self.assertEqual(receipt.operation, "rename_device")
        self.assertEqual(receipt.device_id, "device_1")

    def test_root_revoke_removes_only_selected_root_for_future_policy(self):
        permissions = default_device_permission_profile(device=device())
        updated, receipt = revoke_selected_root(
            permissions=permissions,
            authority=authority(),
            root_ref="docs",
            operation_ref="operation_revoke_root",
            now=NOW,
        )
        self.assertEqual([root.root_ref for root in updated.roots], ["repo"])
        self.assertEqual(receipt.operation, "revoke_root")
        with self.assertRaises(ContractError):
            updated.root_policy("docs")

    def test_device_revoke_uses_trusted_revocation_port_and_requires_correlated_revoked_binding(self):
        original = binding()
        port = RecordingRevocationPort(original)
        revoked, receipt = revoke_device(
            binding=original,
            authority=authority(),
            revocation_port=port,
            operation_ref="operation_revoke_device",
            now=NOW,
        )
        self.assertEqual(port.calls, ["binding_1"])
        self.assertEqual(revoked.state, DeviceLifecycle.REVOKED)
        self.assertEqual(receipt.operation, "revoke_device")

    def test_product_windows_runtime_composition_requires_authorization_and_worktree_probe(self):
        local_device = device()
        profiles = (
            WindowsExecutableProfile(
                profile_ref="python",
                executable_path=r"C:\Python\python.exe",
                required_capabilities=("process.execute",),
            ),
        )
        auth = DeterministicFakeWindowsExecutionAuthorizationPort(capability_refs=("process.execute",))
        worktree = DeterministicWorktreeStatePort(dirty=True)
        with self.assertRaisesRegex(ContractError, "trusted authorization"):
            compose_fail_closed_windows_runtime(
                device=local_device,
                executable_profiles=profiles,
                authorization_port=None,
                worktree_state_port=worktree,
            )
        with self.assertRaisesRegex(ContractError, "worktree-state probe"):
            compose_fail_closed_windows_runtime(
                device=local_device,
                executable_profiles=profiles,
                authorization_port=auth,
                worktree_state_port=None,
            )
        runtime = compose_fail_closed_windows_runtime(
            device=local_device,
            executable_profiles=profiles,
            authorization_port=auth,
            worktree_state_port=worktree,
        )
        self.assertIsNotNone(runtime)

    def test_boundary_flags_are_explicit(self):
        self.assertTrue(DEVICE_STATUS_VISIBLE)
        self.assertTrue(ALLOWED_ROOTS_VISIBLE)
        self.assertTrue(CAPABILITY_POLICY_VISIBLE)
        self.assertTrue(RECENT_ACTIVITY_BOUNDED)
        self.assertTrue(WORKTREE_PROBE_REQUIRED_FOR_REAL_RUNTIME)
        self.assertFalse(CLIENT_MANAGEMENT_MUTATION_AUTHORITY)
        self.assertFalse(RAW_DEVICE_CREDENTIAL_VISIBLE)
        self.assertFalse(RAW_COMMAND_OUTPUT_VISIBLE)
        self.assertFalse(PRODUCTION_REMOTE_CONTROL_CLAIMED)


if __name__ == "__main__":
    unittest.main()
