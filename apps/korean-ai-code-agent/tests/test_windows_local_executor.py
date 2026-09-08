from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

from kagent.contracts import ContractError
from kagent.local_agent import LocalAgentDeviceProfile, LocalAgentPlatform, LocalCommandRequest, LocalRoot
from kagent.windows_local_executor import (
    ADMIN_ELEVATION_SUPPORTED,
    AUTOMATIC_GIT_NETWORK_SUPPORTED,
    PRODUCTION_REMOTE_CONTROL_CLAIMED,
    REAL_WINDOWS_AUTHORIZATION_ADAPTER_CONFIGURED,
    REAL_WINDOWS_SUBPROCESS_EXECUTOR_IMPLEMENTED,
    SHELL_EXECUTION_SUPPORTED,
    UNBOUNDED_ENVIRONMENT_INHERITANCE_SUPPORTED,
    DeterministicFakeWindowsExecutionAuthorizationPort,
    DeterministicWorktreeStatePort,
    TrustedWindowsExecutionGrant,
    WindowsExecutableProfile,
    WindowsExecutionTermination,
    WindowsSubprocessLocalAgentRuntime,
    _bounded_environment,
    _contained_working_directory,
    command_request_fingerprint,
)


def device(root_path: str) -> LocalAgentDeviceProfile:
    return LocalAgentDeviceProfile(
        device_id="device_1",
        workspace_ref="workspace_1",
        platform=LocalAgentPlatform.WINDOWS,
        roots=(LocalRoot(root_ref="repo", windows_path=root_path),),
    )


def command(executable: str, *args: str, timeout_seconds: int = 10) -> LocalCommandRequest:
    return LocalCommandRequest(
        request_id="request_1",
        run_id="run_1",
        device_id="device_1",
        root_ref="repo",
        argv=(executable, *args),
        cwd_relative=".",
        requested_at=datetime.now(timezone.utc),
        timeout_seconds=timeout_seconds,
    )


class WindowsLocalExecutorContractTests(unittest.TestCase):
    def test_shell_and_script_host_profiles_are_prohibited(self):
        for executable in (
            r"C:\Windows\System32\cmd.exe",
            r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
            r"C:\tools\task.cmd",
            r"C:\tools\task.ps1",
        ):
            with self.subTest(executable=executable):
                with self.assertRaises(ContractError):
                    WindowsExecutableProfile(profile_ref="blocked", executable_path=executable)

    def test_network_capable_profile_requires_explicit_network_capability(self):
        with self.assertRaises(ContractError):
            WindowsExecutableProfile(
                profile_ref="python",
                executable_path=r"C:\Python\python.exe",
                required_capabilities=("process.execute",),
                may_access_network=True,
            )
        profile = WindowsExecutableProfile(
            profile_ref="python",
            executable_path=r"C:\Python\python.exe",
            required_capabilities=("process.execute", "network.outbound"),
            may_access_network=True,
        )
        self.assertTrue(profile.may_access_network)

    def test_command_fingerprint_changes_with_argv_or_cwd(self):
        now = datetime.now(timezone.utc)
        base = LocalCommandRequest(
            request_id="request_1",
            run_id="run_1",
            device_id="device_1",
            root_ref="repo",
            argv=(r"C:\Tools\tool.exe", "one"),
            cwd_relative="src",
            requested_at=now,
        )
        changed = LocalCommandRequest(
            request_id="request_1",
            run_id="run_1",
            device_id="device_1",
            root_ref="repo",
            argv=(r"C:\Tools\tool.exe", "two"),
            cwd_relative="src",
            requested_at=now,
        )
        self.assertNotEqual(command_request_fingerprint(base), command_request_fingerprint(changed))

    def test_trusted_grant_is_bound_to_exact_request_profile_device_root_and_capabilities(self):
        now = datetime.now(timezone.utc)
        profile = WindowsExecutableProfile(
            profile_ref="tool",
            executable_path=r"C:\Tools\tool.exe",
            required_capabilities=("process.execute",),
        )
        request = LocalCommandRequest(
            request_id="request_1",
            run_id="run_1",
            device_id="device_1",
            root_ref="repo",
            argv=(r"C:\Tools\tool.exe",),
            cwd_relative=".",
            requested_at=now,
        )
        grant = DeterministicFakeWindowsExecutionAuthorizationPort(capability_refs=("process.execute",)).authorize(
            request=request,
            profile=profile,
            now=now,
        )
        grant.validate(request=request, profile=profile, now=now)
        altered = LocalCommandRequest(
            request_id="request_1",
            run_id="run_1",
            device_id="device_1",
            root_ref="repo",
            argv=(r"C:\Tools\tool.exe", "changed"),
            cwd_relative=".",
            requested_at=now,
        )
        with self.assertRaises(ContractError):
            grant.validate(request=altered, profile=profile, now=now)

    def test_expired_or_capability_incomplete_grant_fails_closed(self):
        now = datetime.now(timezone.utc)
        profile = WindowsExecutableProfile(
            profile_ref="python",
            executable_path=r"C:\Python\python.exe",
            required_capabilities=("process.execute", "network.outbound"),
            may_access_network=True,
        )
        request = LocalCommandRequest(
            request_id="request_1",
            run_id="run_1",
            device_id="device_1",
            root_ref="repo",
            argv=(r"C:\Python\python.exe",),
            cwd_relative=".",
            requested_at=now,
        )
        incomplete = TrustedWindowsExecutionGrant(
            grant_ref="grant_1",
            request_fingerprint=command_request_fingerprint(request),
            device_id="device_1",
            root_ref="repo",
            executable_profile_ref="python",
            capability_refs=("process.execute",),
            p01_approval_ref="approval_1",
            local_policy_ref="policy_1",
            expires_at=now.replace(year=now.year + 1),
        )
        with self.assertRaises(ContractError):
            incomplete.validate(request=request, profile=profile, now=now)
        expired = TrustedWindowsExecutionGrant(
            grant_ref="grant_2",
            request_fingerprint=command_request_fingerprint(request),
            device_id="device_1",
            root_ref="repo",
            executable_profile_ref="python",
            capability_refs=("process.execute", "network.outbound"),
            p01_approval_ref="approval_1",
            local_policy_ref="policy_1",
            expires_at=now,
        )
        with self.assertRaises(ContractError):
            expired.validate(request=request, profile=profile, now=now)

    def test_environment_inheritance_is_bounded_and_ignores_secret_like_host_variables(self):
        old = os.environ.get("GITHUB_TOKEN")
        os.environ["GITHUB_TOKEN"] = "should-not-be-inherited"
        try:
            environment = _bounded_environment()
            self.assertNotIn("GITHUB_TOKEN", environment)
            self.assertNotIn("HOME", environment)
            self.assertNotIn("USERPROFILE", environment)
            self.assertTrue(set(environment).issubset({"SystemRoot", "WINDIR", "SystemDrive", "TEMP", "TMP"}))
        finally:
            if old is None:
                os.environ.pop("GITHUB_TOKEN", None)
            else:
                os.environ["GITHUB_TOKEN"] = old

    @unittest.skipIf(os.name == "nt", "symlink creation privileges vary on Windows runners")
    def test_realpath_containment_rejects_symlink_escape(self):
        with tempfile.TemporaryDirectory() as root_dir, tempfile.TemporaryDirectory() as outside_dir:
            link = Path(root_dir) / "escape"
            link.symlink_to(Path(outside_dir), target_is_directory=True)
            with self.assertRaises(ContractError):
                _contained_working_directory(root_dir, "escape")

    def test_non_windows_real_execution_fails_closed(self):
        if os.name == "nt":
            self.skipTest("covered by Windows execution tests")
        runtime = WindowsSubprocessLocalAgentRuntime(
            device=device(r"C:\workspace\repo"),
            executable_profiles=(WindowsExecutableProfile(profile_ref="tool", executable_path=r"C:\Tools\tool.exe"),),
            authorization_port=DeterministicFakeWindowsExecutionAuthorizationPort(capability_refs=("process.execute",)),
            worktree_state_port=DeterministicWorktreeStatePort(),
        )
        with self.assertRaises(ContractError):
            runtime.execute(command(r"C:\Tools\tool.exe"), now=datetime.now(timezone.utc))

    def test_boundary_nonclaims_are_explicit(self):
        self.assertTrue(REAL_WINDOWS_SUBPROCESS_EXECUTOR_IMPLEMENTED)
        self.assertFalse(REAL_WINDOWS_AUTHORIZATION_ADAPTER_CONFIGURED)
        self.assertFalse(SHELL_EXECUTION_SUPPORTED)
        self.assertFalse(UNBOUNDED_ENVIRONMENT_INHERITANCE_SUPPORTED)
        self.assertFalse(ADMIN_ELEVATION_SUPPORTED)
        self.assertFalse(AUTOMATIC_GIT_NETWORK_SUPPORTED)
        self.assertFalse(PRODUCTION_REMOTE_CONTROL_CLAIMED)


@unittest.skipUnless(os.name == "nt", "real subprocess contract is Windows-first")
class WindowsLocalExecutorLiveProcessTests(unittest.TestCase):
    def _runtime(self, root_path: str) -> WindowsSubprocessLocalAgentRuntime:
        executable = str(Path(sys.executable).resolve())
        profile = WindowsExecutableProfile(
            profile_ref="python_test",
            executable_path=executable,
            required_capabilities=("process.execute", "network.outbound"),
            may_access_network=True,
        )
        return WindowsSubprocessLocalAgentRuntime(
            device=device(root_path),
            executable_profiles=(profile,),
            authorization_port=DeterministicFakeWindowsExecutionAuthorizationPort(
                capability_refs=("process.execute", "network.outbound")
            ),
            worktree_state_port=DeterministicWorktreeStatePort(dirty=True),
        )

    def test_real_user_level_process_executes_without_shell_and_preserves_dirty_state(self):
        with tempfile.TemporaryDirectory() as root_dir:
            runtime = self._runtime(root_dir)
            request = command(str(Path(sys.executable).resolve()), "-c", "print('windows-local-ok')")
            receipt = runtime.execute_with_receipt(request, now=datetime.now(timezone.utc))
            self.assertEqual(receipt.termination, WindowsExecutionTermination.EXITED)
            self.assertEqual(receipt.result.exit_code, 0)
            self.assertIn("windows-local-ok", receipt.result.stdout)
            self.assertTrue(receipt.result.dirty_worktree_before)
            self.assertTrue(receipt.result.dirty_worktree_after)
            rendered = receipt.safe_dict()
            self.assertFalse(rendered["shell"])
            self.assertFalse(rendered["admin_elevation"])
            self.assertEqual(rendered["environment_inheritance"], "bounded_allowlist")

    def test_real_output_is_bounded_while_pipes_are_fully_drained(self):
        with tempfile.TemporaryDirectory() as root_dir:
            runtime = self._runtime(root_dir)
            request = command(str(Path(sys.executable).resolve()), "-c", "print('x' * 20000)")
            receipt = runtime.execute_with_receipt(request, now=datetime.now(timezone.utc))
            self.assertEqual(receipt.termination, WindowsExecutionTermination.EXITED)
            self.assertEqual(len(receipt.result.stdout), 8192)
            self.assertTrue(receipt.result.stdout_truncated)

    def test_timeout_is_distinct_from_explicit_cancel(self):
        with tempfile.TemporaryDirectory() as root_dir:
            runtime = self._runtime(root_dir)
            request = command(
                str(Path(sys.executable).resolve()),
                "-c",
                "import time; time.sleep(3)",
                timeout_seconds=1,
            )
            receipt = runtime.execute_with_receipt(request, now=datetime.now(timezone.utc))
            self.assertEqual(receipt.termination, WindowsExecutionTermination.TIMED_OUT)
            self.assertFalse(receipt.result.cancelled)
            self.assertIsNone(receipt.result.exit_code)

    def test_active_process_can_be_cancelled(self):
        with tempfile.TemporaryDirectory() as root_dir:
            runtime = self._runtime(root_dir)
            request = command(
                str(Path(sys.executable).resolve()),
                "-c",
                "import time; time.sleep(30)",
                timeout_seconds=60,
            )
            holder: dict[str, object] = {}

            def run() -> None:
                holder["receipt"] = runtime.execute_with_receipt(request, now=datetime.now(timezone.utc))

            thread = threading.Thread(target=run)
            thread.start()
            deadline = time.time() + 5
            while request.request_id not in runtime.active_request_ids() and time.time() < deadline:
                time.sleep(0.02)
            self.assertIn(request.request_id, runtime.active_request_ids())
            runtime.cancel(request.request_id)
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            receipt = holder["receipt"]
            self.assertEqual(receipt.termination, WindowsExecutionTermination.CANCELLED)
            self.assertTrue(receipt.result.cancelled)
            self.assertIsNone(receipt.result.exit_code)


if __name__ == "__main__":
    unittest.main()
