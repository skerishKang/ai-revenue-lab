from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from kagent.contracts import ContractError
from kagent.local_agent import LocalAgentDeviceProfile, LocalAgentPlatform, LocalCommandRequest, LocalRoot
from kagent.windows_job_object import (
    JOB_OBJECT_ADMIN_ELEVATION_REQUIRED,
    JOB_OBJECT_NATIVE_PRIMITIVE,
    PYWIN32_DEPENDENCY_ADDED,
    WINDOWS_JOB_OBJECT_IMPLEMENTED,
    WindowsJobObject,
    launch_job_bound_process,
    windows_process_is_alive,
)
from kagent.windows_local_executor import (
    ADMIN_ELEVATION_SUPPORTED,
    SECOND_APPROVAL_AUTHORITY,
    SECOND_FILESYSTEM_AUTHORITY,
    SECOND_PROCESS_AUTHORITY,
    WINDOWS_JOB_OBJECT_PROCESS_TREE_TERMINATION,
    DeterministicFakeWindowsExecutionAuthorizationPort,
    DeterministicWorktreeStatePort,
    WindowsExecutableProfile,
    WindowsExecutionTermination,
    WindowsSubprocessLocalAgentRuntime,
    _bounded_environment,
    _contained_working_directory,
)

# Spawns parent -> child -> grandchild, each recording its own PID and then
# sleeping. Written to a file so the child processes never depend on argv size
# limits or on shell interpretation.
_TREE_SCRIPT = """
import os, subprocess, sys, time

role, pid_file, child_script, depth = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
with open(pid_file, "w", encoding="utf-8") as handle:
    handle.write(str(os.getpid()))
if depth > 0:
    subprocess.Popen(
        [sys.executable, child_script, "child" if role == "parent" else "grandchild", pid_file + ".child", child_script, str(depth - 1)],
        shell=False,
    )
time.sleep(120)
"""

_TERMINAL_SURVIVOR_POLL_SECONDS = 10.0


def _write_tree_script(root_dir: str) -> str:
    path = Path(root_dir) / "process_tree_fixture.py"
    path.write_text(_TREE_SCRIPT, encoding="utf-8")
    return str(path)


def _device(root_path: str) -> LocalAgentDeviceProfile:
    return LocalAgentDeviceProfile(
        device_id="device_3081",
        workspace_ref="workspace_3081",
        platform=LocalAgentPlatform.WINDOWS,
        roots=(LocalRoot(root_ref="repo", windows_path=root_path),),
    )


def _request(executable: str, *args: str, timeout_seconds: int, request_id: str) -> LocalCommandRequest:
    return LocalCommandRequest(
        request_id=request_id,
        run_id="run_3081",
        device_id="device_3081",
        root_ref="repo",
        argv=(executable, *args),
        cwd_relative=".",
        requested_at=datetime.now(timezone.utc),
        timeout_seconds=timeout_seconds,
    )


def _runtime(root_path: str) -> WindowsSubprocessLocalAgentRuntime:
    executable = str(Path(sys.executable).resolve())
    return WindowsSubprocessLocalAgentRuntime(
        device=_device(root_path),
        executable_profiles=(
            WindowsExecutableProfile(
                profile_ref="python_3081",
                executable_path=executable,
                required_capabilities=("process.execute", "network.outbound"),
                may_access_network=True,
            ),
        ),
        authorization_port=DeterministicFakeWindowsExecutionAuthorizationPort(
            capability_refs=("process.execute", "network.outbound")
        ),
        worktree_state_port=DeterministicWorktreeStatePort(dirty=False),
    )


def _tree_argv(root_dir: str, *, depth: int) -> tuple[str, ...]:
    script = _write_tree_script(root_dir)
    pid_file = str(Path(root_dir) / "tree.pid")
    return (str(Path(sys.executable).resolve()), script, "parent", pid_file, script, str(depth))


def _read_pid(path: Path) -> int:
    return int(path.read_text(encoding="utf-8").strip())


def _await_tree_pids(root_dir: str) -> tuple[int, int, int]:
    """Wait until the parent, child, and grandchild PID files all exist."""
    parent_file = Path(root_dir) / "tree.pid"
    child_file = Path(root_dir) / "tree.pid.child"
    grandchild_file = Path(root_dir) / "tree.pid.child.child"
    deadline = time.time() + 20
    while time.time() < deadline:
        if parent_file.exists() and child_file.exists() and grandchild_file.exists():
            try:
                return _read_pid(parent_file), _read_pid(child_file), _read_pid(grandchild_file)
            except (OSError, ValueError):
                pass
        time.sleep(0.05)
    raise AssertionError("process tree did not reach parent -> child -> grandchild")


def _await_descendants_gone(pids: tuple[int, ...]) -> tuple[int, ...]:
    """Poll until every descendant PID is no longer alive; return survivors."""
    deadline = time.time() + _TERMINAL_SURVIVOR_POLL_SECONDS
    survivors = pids
    while time.time() < deadline:
        survivors = tuple(pid for pid in survivors if windows_process_is_alive(pid))
        if not survivors:
            return ()
        time.sleep(0.1)
    return survivors


def _await_parent_reaped(process: subprocess.Popen[str]) -> bool:
    """Wait for the immediate child exit status to be observable on the Popen handle."""
    deadline = time.time() + _TERMINAL_SURVIVOR_POLL_SECONDS
    while time.time() < deadline:
        if process.poll() is not None:
            return True
        time.sleep(0.05)
    return False


class WindowsJobObjectContractTests(unittest.TestCase):
    """Cross-platform contract tests. These must never pass off Windows-only
    behaviour as cross-platform capability."""

    def test_native_primitive_and_dependency_posture_are_explicit(self):
        self.assertTrue(WINDOWS_JOB_OBJECT_IMPLEMENTED)
        self.assertEqual(JOB_OBJECT_NATIVE_PRIMITIVE, "windows_job_object")
        self.assertFalse(PYWIN32_DEPENDENCY_ADDED)
        self.assertFalse(JOB_OBJECT_ADMIN_ELEVATION_REQUIRED)
        self.assertTrue(WINDOWS_JOB_OBJECT_PROCESS_TREE_TERMINATION)
        self.assertEqual(SECOND_PROCESS_AUTHORITY, 0)
        self.assertEqual(SECOND_APPROVAL_AUTHORITY, 0)
        self.assertEqual(SECOND_FILESYSTEM_AUTHORITY, 0)

    def test_admin_elevation_is_never_required(self):
        self.assertFalse(ADMIN_ELEVATION_SUPPORTED)

    def test_non_windows_platform_fails_closed_instead_of_faking_containment(self):
        if os.name == "nt":
            self.skipTest("non-Windows fail-closed contract is exercised off Windows")
        with self.assertRaises(ContractError):
            WindowsJobObject()
        with self.assertRaises(ContractError):
            launch_job_bound_process(
                ["/bin/true"],
                cwd=os.getcwd(),
                environment=_bounded_environment(),
            )
        with self.assertRaises(ContractError):
            windows_process_is_alive(1)

    def test_selected_root_cwd_policy_is_unchanged(self):
        with tempfile.TemporaryDirectory() as root_dir:
            resolved_root = _contained_working_directory(root_dir, ".")
            self.assertEqual(Path(resolved_root).resolve(), Path(root_dir).resolve())
            with self.assertRaises(ContractError):
                _contained_working_directory(root_dir, "..")
            # Pre-existing behaviour, deliberately not changed by #3081: a
            # non-existent relative cwd surfaces as FileNotFoundError from
            # resolve(strict=True) before containment is evaluated.
            with self.assertRaises(FileNotFoundError):
                _contained_working_directory(root_dir, "does-not-exist")

    def test_environment_allowlist_is_unchanged(self):
        environment = _bounded_environment()
        self.assertTrue(set(environment).issubset({"SystemRoot", "WINDIR", "SystemDrive", "TEMP", "TMP"}))


@unittest.skipUnless(os.name == "nt", "real Windows process-tree termination requires Windows")
class WindowsProcessTreeTerminationTests(unittest.TestCase):
    def test_timeout_kills_child_and_grandchild_and_leaves_no_survivor(self):
        with tempfile.TemporaryDirectory() as root_dir:
            runtime = _runtime(root_dir)
            holder: dict[str, object] = {}

            def run() -> None:
                holder["receipt"] = runtime.execute_with_receipt(
                    _request(*_tree_argv(root_dir, depth=2), timeout_seconds=1, request_id="timeout_tree"),
                    now=datetime.now(timezone.utc),
                )

            thread = threading.Thread(target=run)
            thread.start()
            parent_pid, child_pid, grandchild_pid = _await_tree_pids(root_dir)
            thread.join(timeout=30)
            self.assertFalse(thread.is_alive())
            receipt = holder["receipt"]
            self.assertEqual(receipt.termination, WindowsExecutionTermination.TIMED_OUT)
            self.assertFalse(receipt.result.cancelled)
            self.assertEqual(_await_descendants_gone((parent_pid, child_pid, grandchild_pid)), ())
            self.assertEqual(runtime.active_request_ids(), ())

    def test_explicit_cancel_kills_child_and_grandchild_and_leaves_no_survivor(self):
        with tempfile.TemporaryDirectory() as root_dir:
            runtime = _runtime(root_dir)
            holder: dict[str, object] = {}
            request = _request(*_tree_argv(root_dir, depth=2), timeout_seconds=120, request_id="cancel_tree")

            def run() -> None:
                holder["receipt"] = runtime.execute_with_receipt(request, now=datetime.now(timezone.utc))

            thread = threading.Thread(target=run)
            thread.start()
            parent_pid, child_pid, grandchild_pid = _await_tree_pids(root_dir)
            self.assertIn(request.request_id, runtime.active_request_ids())
            runtime.cancel(request.request_id)
            thread.join(timeout=30)
            self.assertFalse(thread.is_alive())
            receipt = holder["receipt"]
            self.assertEqual(receipt.termination, WindowsExecutionTermination.CANCELLED)
            self.assertTrue(receipt.result.cancelled)
            self.assertEqual(_await_descendants_gone((parent_pid, child_pid, grandchild_pid)), ())
            self.assertEqual(runtime.active_request_ids(), ())

    def test_terminal_cleanup_leaves_zero_descendant_survivors(self):
        with tempfile.TemporaryDirectory() as root_dir:
            runtime = _runtime(root_dir)
            request = _request(
                *_tree_argv(root_dir, depth=2),
                timeout_seconds=120,
                request_id="terminal_tree",
            )
            holder: dict[str, object] = {}

            def run() -> None:
                holder["receipt"] = runtime.execute_with_receipt(request, now=datetime.now(timezone.utc))

            thread = threading.Thread(target=run)
            thread.start()
            parent_pid, child_pid, grandchild_pid = _await_tree_pids(root_dir)
            runtime.cancel(request.request_id)
            thread.join(timeout=30)
            self.assertFalse(thread.is_alive())
            self.assertEqual(_await_descendants_gone((parent_pid, child_pid, grandchild_pid)), ())

    def test_job_close_kills_remaining_tree_members(self):
        with tempfile.TemporaryDirectory() as root_dir:
            environment = _bounded_environment()
            script = _write_tree_script(root_dir)
            bound = launch_job_bound_process(
                [str(Path(sys.executable).resolve()), script, "parent", str(Path(root_dir) / "close.pid"), script, "2"],
                cwd=root_dir,
                environment=environment,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            parent_file = Path(root_dir) / "close.pid"
            child_file = Path(root_dir) / "close.pid.child"
            grandchild_file = Path(root_dir) / "close.pid.child.child"
            deadline = time.time() + 20
            while time.time() < deadline and not (
                parent_file.exists() and child_file.exists() and grandchild_file.exists()
            ):
                time.sleep(0.05)
            self.assertTrue(parent_file.exists() and child_file.exists() and grandchild_file.exists())
            pids = (_read_pid(parent_file), _read_pid(child_file), _read_pid(grandchild_file))
            self.assertTrue(any(windows_process_is_alive(pid) for pid in pids))
            # Closing the kill-on-close handle alone must reap the tree.
            bound.job.close()
            self.assertEqual(_await_descendants_gone(pids), ())
            self.assertEqual(_await_parent_reaped(bound.process), True)

    def test_normal_success_is_not_false_killed(self):
        with tempfile.TemporaryDirectory() as root_dir:
            runtime = _runtime(root_dir)
            receipt = runtime.execute_with_receipt(
                _request(
                    str(Path(sys.executable).resolve()),
                    "-c",
                    "print('job-object-normal-ok')",
                    timeout_seconds=60,
                    request_id="normal_tree",
                ),
                now=datetime.now(timezone.utc),
            )
            self.assertEqual(receipt.termination, WindowsExecutionTermination.EXITED)
            self.assertEqual(receipt.result.exit_code, 0)
            self.assertIn("job-object-normal-ok", receipt.result.stdout)
            self.assertFalse(receipt.result.cancelled)
            rendered = receipt.safe_dict()
            self.assertFalse(rendered["shell"])
            self.assertFalse(rendered["admin_elevation"])
            self.assertEqual(rendered["environment_inheritance"], "bounded_allowlist")

    def test_bounded_output_and_timeout_distinction_survive_job_containment(self):
        with tempfile.TemporaryDirectory() as root_dir:
            runtime = _runtime(root_dir)
            truncated = runtime.execute_with_receipt(
                _request(
                    str(Path(sys.executable).resolve()),
                    "-c",
                    "print('x' * 20000)",
                    timeout_seconds=60,
                    request_id="bounded_tree",
                ),
                now=datetime.now(timezone.utc),
            )
            self.assertEqual(truncated.termination, WindowsExecutionTermination.EXITED)
            self.assertEqual(len(truncated.result.stdout), 8192)
            self.assertTrue(truncated.result.stdout_truncated)

            timed_out = runtime.execute_with_receipt(
                _request(
                    str(Path(sys.executable).resolve()),
                    "-c",
                    "import time; time.sleep(30)",
                    timeout_seconds=1,
                    request_id="timeout_plain",
                ),
                now=datetime.now(timezone.utc),
            )
            self.assertEqual(timed_out.termination, WindowsExecutionTermination.TIMED_OUT)
            self.assertIsNone(timed_out.result.exit_code)

    def test_p01_authorization_path_is_unchanged_and_still_fails_closed(self):
        with tempfile.TemporaryDirectory() as root_dir:
            authorization = DeterministicFakeWindowsExecutionAuthorizationPort(
                capability_refs=("process.execute", "network.outbound")
            )
            executable = str(Path(sys.executable).resolve())
            runtime = WindowsSubprocessLocalAgentRuntime(
                device=_device(root_dir),
                executable_profiles=(
                    WindowsExecutableProfile(
                        profile_ref="python_3081",
                        executable_path=executable,
                        required_capabilities=("process.execute", "network.outbound"),
                        may_access_network=True,
                    ),
                ),
                authorization_port=authorization,
                worktree_state_port=DeterministicWorktreeStatePort(dirty=False),
            )
            receipt = runtime.execute_with_receipt(
                _request(
                    executable,
                    "-c",
                    "print('p01-ok')",
                    timeout_seconds=60,
                    request_id="p01_tree",
                ),
                now=datetime.now(timezone.utc),
            )
            self.assertEqual(authorization.calls, ["p01_tree"])
            self.assertEqual(receipt.authorization_ref, "fake_grant_p01_tree")
            self.assertIn("p01-ok", receipt.result.stdout)

            # A request whose executable is outside the trusted profile allowlist
            # must still fail closed before any process or job is created.
            with self.assertRaises(ContractError):
                runtime.execute_with_receipt(
                    _request(
                        r"C:\Windows\System32\cmd.exe",
                        "/c",
                        "echo nope",
                        timeout_seconds=60,
                        request_id="p01_blocked",
                    ),
                    now=datetime.now(timezone.utc),
                )
            self.assertEqual(authorization.calls, ["p01_tree"])
            self.assertEqual(runtime.active_request_ids(), ())

    def test_shell_and_script_host_executables_remain_prohibited(self):
        for executable in (
            r"C:\Windows\System32\cmd.exe",
            r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
            r"C:\tools\task.ps1",
        ):
            with self.subTest(executable=executable), self.assertRaises(ContractError):
                WindowsExecutableProfile(profile_ref="blocked_3081", executable_path=executable)


if __name__ == "__main__":
    unittest.main()
