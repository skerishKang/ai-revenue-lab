from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from kagent.contracts import ContractError
from kagent.local_agent import (
    ADMIN_ELEVATION_DEFAULT,
    AUTOMATIC_GIT_PUSH_MERGE_DEPLOY,
    OUTBOUND_CONNECTION_ONLY,
    PUBLIC_INBOUND_PORT_REQUIRED,
    RAW_HOST_CREDENTIAL_DISCOVERY,
    REAL_LOCAL_HOST_EXECUTION_CONFIGURED,
    WINDOWS_FIRST_LOCAL_AGENT,
    DeterministicFakeLocalAgentRuntime,
    LocalAgentDeviceProfile,
    LocalAgentPlatform,
    LocalCommandRequest,
    LocalCommandResult,
    LocalRoot,
    UnconfiguredLocalAgentRuntime,
)


NOW = datetime(2026, 9, 3, 6, 0, tzinfo=timezone.utc)


def profile(**kwargs):
    values = dict(
        device_id="device_local_1",
        workspace_ref="workspace_1",
        platform=LocalAgentPlatform.WINDOWS,
        roots=(
            LocalRoot(root_ref="repo", windows_path=r"E:\workspace\repo"),
            LocalRoot(root_ref="docs", windows_path=r"D:\Documents\Padiem"),
        ),
    )
    values.update(kwargs)
    return LocalAgentDeviceProfile(**values)


def request(**kwargs):
    values = dict(
        request_id="local_command_1",
        run_id="run_1",
        device_id="device_local_1",
        root_ref="repo",
        argv=("python", "-m", "pytest"),
        cwd_relative="tests",
        requested_at=NOW,
        timeout_seconds=120,
    )
    values.update(kwargs)
    return LocalCommandRequest(**values)


class LocalAgentContractTests(unittest.TestCase):
    def test_device_profile_is_windows_first_selected_roots_only(self):
        rendered = profile().safe_dict()
        self.assertEqual(rendered["platform"], "windows")
        self.assertEqual(len(rendered["roots"]), 2)
        self.assertTrue(all(root["user_selected"] for root in rendered["roots"]))
        self.assertTrue(all(not root["whole_pc"] for root in rendered["roots"]))
        self.assertTrue(rendered["outbound_connection_only"])
        self.assertFalse(rendered["public_inbound_port"])
        self.assertFalse(rendered["admin_default"])
        self.assertFalse(rendered["credential_discovery"])

    def test_root_must_be_absolute_drive_path_without_traversal_or_unc(self):
        with self.assertRaises(ContractError):
            LocalRoot(root_ref="bad", windows_path=r"relative\repo")
        with self.assertRaises(ContractError):
            LocalRoot(root_ref="bad", windows_path=r"E:\workspace\..\secret")
        with self.assertRaises(ContractError):
            LocalRoot(root_ref="bad", windows_path=r"\\server\share\repo")

    def test_duplicate_root_refs_or_paths_fail_closed(self):
        with self.assertRaises(ContractError):
            profile(
                roots=(
                    LocalRoot(root_ref="repo", windows_path=r"E:\workspace\repo"),
                    LocalRoot(root_ref="repo", windows_path=r"D:\other"),
                )
            )
        with self.assertRaises(ContractError):
            profile(
                roots=(
                    LocalRoot(root_ref="repo", windows_path=r"E:\workspace\repo"),
                    LocalRoot(root_ref="repo2", windows_path=r"e:\WORKSPACE\repo"),
                )
            )

    def test_command_request_is_direct_process_and_cwd_cannot_escape_selected_root(self):
        rendered = request().safe_dict()
        self.assertTrue(rendered["direct_process"])
        self.assertFalse(rendered["shell_authority"])
        self.assertFalse(rendered["admin_elevation"])
        self.assertFalse(rendered["automatic_git_network"])
        with self.assertRaises(ContractError):
            request(cwd_relative=r"..\outside")
        with self.assertRaises(ContractError):
            request(cwd_relative=r"C:\Windows")

    def test_fake_runtime_resolves_working_directory_inside_selected_root(self):
        fake = DeterministicFakeLocalAgentRuntime(profile())
        resolved = fake.resolve_working_directory(request())
        self.assertEqual(resolved.casefold(), r"e:\workspace\repo\tests".casefold())

    def test_fake_runtime_executes_no_host_process_and_preserves_dirty_worktree(self):
        fake = DeterministicFakeLocalAgentRuntime(profile(), dirty_roots=("repo",))
        result = fake.execute(request(), now=NOW + timedelta(seconds=1))
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.stdout, "fake-local-agent:python")
        self.assertFalse(result.cancelled)
        self.assertTrue(result.dirty_worktree_before)
        self.assertTrue(result.dirty_worktree_after)
        rendered = result.safe_dict()
        self.assertFalse(rendered["automatic_git_clean_reset"])
        self.assertFalse(rendered["raw_host_credentials"])

    def test_command_cancellation_is_terminal_for_the_fake_execution(self):
        fake = DeterministicFakeLocalAgentRuntime(profile())
        fake.cancel("local_command_1")
        result = fake.execute(request(), now=NOW + timedelta(seconds=1))
        self.assertTrue(result.cancelled)
        self.assertIsNone(result.exit_code)
        self.assertEqual(result.stderr, "cancelled")

    def test_device_or_root_mismatch_fails_closed(self):
        fake = DeterministicFakeLocalAgentRuntime(profile())
        with self.assertRaises(ContractError):
            fake.execute(request(device_id="device_other"), now=NOW + timedelta(seconds=1))
        with self.assertRaises(ContractError):
            fake.execute(request(root_ref="missing"), now=NOW + timedelta(seconds=1))

    def test_output_is_bounded_and_reports_truncation(self):
        result = LocalCommandResult(
            request_id="local_command_1",
            run_id="run_1",
            device_id="device_local_1",
            root_ref="repo",
            started_at=NOW,
            ended_at=NOW,
            exit_code=0,
            stdout="x" * 9000,
            stderr="y" * 9000,
            cancelled=False,
            dirty_worktree_before=False,
            dirty_worktree_after=False,
        )
        self.assertEqual(len(result.stdout), 8192)
        self.assertEqual(len(result.stderr), 8192)
        self.assertTrue(result.stdout_truncated)
        self.assertTrue(result.stderr_truncated)

    def test_non_windows_fake_runtime_is_not_claimed_complete(self):
        mac_profile = profile(platform=LocalAgentPlatform.MACOS)
        with self.assertRaises(ContractError):
            DeterministicFakeLocalAgentRuntime(mac_profile)

    def test_unconfigured_real_runtime_fails_closed_and_authority_claims_remain_false(self):
        runtime = UnconfiguredLocalAgentRuntime()
        with self.assertRaises(ContractError):
            runtime.execute(request(), now=NOW)
        with self.assertRaises(ContractError):
            runtime.cancel("local_command_1")
        self.assertTrue(WINDOWS_FIRST_LOCAL_AGENT)
        self.assertTrue(OUTBOUND_CONNECTION_ONLY)
        self.assertFalse(PUBLIC_INBOUND_PORT_REQUIRED)
        self.assertFalse(REAL_LOCAL_HOST_EXECUTION_CONFIGURED)
        self.assertFalse(ADMIN_ELEVATION_DEFAULT)
        self.assertFalse(RAW_HOST_CREDENTIAL_DISCOVERY)
        self.assertFalse(AUTOMATIC_GIT_PUSH_MERGE_DEPLOY)


if __name__ == "__main__":
    unittest.main()
