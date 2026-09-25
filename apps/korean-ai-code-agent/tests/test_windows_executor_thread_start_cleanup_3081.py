"""Regression evidence for the #3081 drain-thread setup cleanup hole.

The canonical Windows executor inserted the Job-bound child into ``_active``
and only then started the stdout/stderr drain threads, all *before* entering the
``try``/``finally`` that performs terminal cleanup. A ``Thread.start()`` failure
therefore bypassed that cleanup entirely, which could leave:

- the ``request_id`` permanently stuck in ``_active``;
- the Job handle unclosed by the executor frame, so
  ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`` never fired;
- a live child process tree outliving the failed request.

These tests drive real Windows ``parent -> child -> grandchild`` trees and force
``Thread.start()`` to fail at a chosen position, then assert that the same
terminal cleanup a timeout or an explicit cancel receives still runs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import threading
import time
from typing import Self
import unittest

from kagent import windows_local_executor
from kagent.local_agent import LocalAgentDeviceProfile, LocalAgentPlatform, LocalCommandRequest, LocalRoot
from kagent.windows_job_object import windows_process_is_alive
from kagent.windows_local_executor import (
    DeterministicFakeWindowsExecutionAuthorizationPort,
    DeterministicWorktreeStatePort,
    WindowsExecutableProfile,
    WindowsSubprocessLocalAgentRuntime,
)

# Same recursive fixture shape as the process-tree evidence: each level records
# its own PID and then sleeps, so a survivor is observable by PID alone.
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

_SURVIVOR_POLL_SECONDS = 10.0


def _write_tree_script(root_dir: str) -> str:
    path = Path(root_dir) / "thread_start_tree_fixture.py"
    path.write_text(_TREE_SCRIPT, encoding="utf-8")
    return str(path)


def _device(root_path: str) -> LocalAgentDeviceProfile:
    return LocalAgentDeviceProfile(
        device_id="device_3081_setup",
        workspace_ref="workspace_3081_setup",
        platform=LocalAgentPlatform.WINDOWS,
        roots=(LocalRoot(root_ref="repo", windows_path=root_path),),
    )


def _runtime(root_path: str) -> WindowsSubprocessLocalAgentRuntime:
    executable = str(Path(sys.executable).resolve())
    return WindowsSubprocessLocalAgentRuntime(
        device=_device(root_path),
        executable_profiles=(
            WindowsExecutableProfile(
                profile_ref="python_3081_setup",
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


def _tree_request(root_dir: str, *, request_id: str) -> LocalCommandRequest:
    script = _write_tree_script(root_dir)
    return LocalCommandRequest(
        request_id=request_id,
        run_id="run_3081_setup",
        device_id="device_3081_setup",
        root_ref="repo",
        argv=(
            str(Path(sys.executable).resolve()),
            script,
            "parent",
            str(Path(root_dir) / "setup.pid"),
            script,
            "2",
        ),
        cwd_relative=".",
        requested_at=datetime.now(timezone.utc),
        timeout_seconds=60,
    )


def _await_tree_pids(root_dir: str) -> tuple[int, int, int]:
    """Wait for the parent, child, and grandchild PID files."""
    parent_file = Path(root_dir) / "setup.pid"
    child_file = Path(root_dir) / "setup.pid.child"
    grandchild_file = Path(root_dir) / "setup.pid.child.child"
    deadline = time.time() + 20
    while time.time() < deadline:
        if parent_file.exists() and child_file.exists() and grandchild_file.exists():
            try:
                return (
                    int(parent_file.read_text(encoding="utf-8").strip()),
                    int(child_file.read_text(encoding="utf-8").strip()),
                    int(grandchild_file.read_text(encoding="utf-8").strip()),
                )
            except (OSError, ValueError):
                pass
        time.sleep(0.05)
    raise AssertionError("process tree did not reach parent -> child -> grandchild")


def _await_descendants_gone(pids: tuple[int, ...]) -> tuple[int, ...]:
    """Poll until no descendant PID is alive; return the survivors."""
    deadline = time.time() + _SURVIVOR_POLL_SECONDS
    survivors = pids
    while time.time() < deadline:
        survivors = tuple(pid for pid in survivors if windows_process_is_alive(pid))
        if not survivors:
            return ()
        time.sleep(0.1)
    return survivors


class _FailingThreadStart:
    """Patch ``threading.Thread.start`` to fail on a chosen 1-based call index.

    ``fail_on_index=1`` models the stdout drain thread failing to start, i.e.
    before any thread is running. ``fail_on_index=2`` models the harder partial
    case: stdout started, stderr failed, so cleanup must join exactly one thread
    and must not try to join the thread that never started.

    ``gate`` runs immediately before the failure is raised. It is used to wait
    until the real process tree is fully up, so the evidence proves a live
    ``parent -> child -> grandchild`` tree was reaped by the cleanup rather than
    merely that a process which never ran was closed.
    """

    def __init__(self, fail_on_index: int, *, gate: object = None) -> None:
        self._fail_on_index = fail_on_index
        self._gate = gate
        self._calls = 0
        self._original_start = threading.Thread.start
        self._started: list[threading.Thread] = []

    def __enter__(self) -> Self:
        patcher = self

        def _start(thread: threading.Thread, *args: object, **kwargs: object) -> None:
            patcher._calls += 1
            if patcher._calls == patcher._fail_on_index:
                if patcher._gate is not None:
                    patcher._gate()
                raise RuntimeError("simulated drain thread start failure")
            patcher._original_start(thread, *args, **kwargs)
            patcher._started.append(thread)

        self._patched_start = _start
        threading.Thread.start = _start  # type: ignore[method-assign]
        return self

    def __exit__(self, *_exc: object) -> None:
        threading.Thread.start = self._original_start  # type: ignore[method-assign]

    @property
    def successfully_started(self) -> list[threading.Thread]:
        return list(self._started)


def _await_threads_settled(threads: list[threading.Thread], *, timeout: float = 5.0) -> list[threading.Thread]:
    """Return the threads still alive after a bounded wait."""
    deadline = time.time() + timeout
    remaining = list(threads)
    while remaining and time.time() < deadline:
        remaining = [thread for thread in remaining if thread.is_alive()]
        if not remaining:
            return []
        time.sleep(0.05)
    return [thread for thread in remaining if thread.is_alive()]


def _capture_jobs(monkey_target: object) -> list[object]:
    """Collect every Job object the executor created during one call."""
    captured: list[object] = []
    original = monkey_target.launch_job_bound_process  # type: ignore[attr-defined]

    def _recording_launch(*args: object, **kwargs: object) -> object:
        bound = original(*args, **kwargs)
        captured.append(bound.job)
        return bound

    monkey_target.launch_job_bound_process = _recording_launch  # type: ignore[attr-defined]
    return captured


class WindowsExecutorThreadStartCleanupTests(unittest.TestCase):
    """The setup region must share the terminal cleanup region."""

    def setUp(self) -> None:
        if sys.platform != "win32":
            self.skipTest("real Windows Job Object containment evidence requires Windows")

    def test_first_drain_thread_start_failure_still_runs_terminal_cleanup(self):
        """stdout_thread.start() failure: no thread ever started."""
        with tempfile.TemporaryDirectory() as root_dir:
            runtime = _runtime(root_dir)
            jobs = _capture_jobs(windows_local_executor)
            request = _tree_request(root_dir, request_id="setup_fail_first")
            pids: list[tuple[int, ...]] = []

            def _gate() -> None:
                pids.append(_await_tree_pids(root_dir))

            with (
                _FailingThreadStart(fail_on_index=1, gate=_gate) as patcher,
                self.assertRaises(RuntimeError),
            ):
                runtime.execute_with_receipt(request, now=datetime.now(timezone.utc))
            self.assertEqual(patcher.successfully_started, [])

            self.assertEqual(len(pids), 1)
            self.assertEqual(_await_descendants_gone(pids[0]), ())
            self.assertEqual(runtime.active_request_ids(), ())
            self.assertEqual(len(jobs), 1)
            self.assertTrue(jobs[0].closed)

    def test_second_drain_thread_start_failure_joins_only_started_thread(self):
        """stderr_thread.start() failure: exactly one thread started."""
        with tempfile.TemporaryDirectory() as root_dir:
            runtime = _runtime(root_dir)
            jobs = _capture_jobs(windows_local_executor)
            request = _tree_request(root_dir, request_id="setup_fail_second")
            pids: list[tuple[int, ...]] = []

            def _gate() -> None:
                pids.append(_await_tree_pids(root_dir))

            with (
                _FailingThreadStart(fail_on_index=2, gate=_gate) as patcher,
                self.assertRaises(RuntimeError),
            ):
                runtime.execute_with_receipt(request, now=datetime.now(timezone.utc))
            self.assertEqual(len(patcher.successfully_started), 1)
            started = list(patcher.successfully_started)

            self.assertEqual(_await_threads_settled(started), [])
            self.assertEqual(len(pids), 1)
            self.assertEqual(_await_descendants_gone(pids[0]), ())
            self.assertEqual(runtime.active_request_ids(), ())
            self.assertEqual(len(jobs), 1)
            self.assertTrue(jobs[0].closed)

    def test_full_tree_setup_failure_leaves_no_survivor_and_no_leak(self):
        """A real ``parent -> child -> grandchild`` tree cannot outlive the
        request when drain-thread setup fails."""
        with tempfile.TemporaryDirectory() as root_dir:
            runtime = _runtime(root_dir)
            jobs = _capture_jobs(windows_local_executor)
            request = _tree_request(root_dir, request_id="setup_fail_full_tree")
            pids: list[tuple[int, ...]] = []

            def _gate() -> None:
                pids.append(_await_tree_pids(root_dir))

            with (
                _FailingThreadStart(fail_on_index=1, gate=_gate),
                self.assertRaises(RuntimeError),
            ):
                runtime.execute_with_receipt(request, now=datetime.now(timezone.utc))

            self.assertEqual(len(pids), 1)
            self.assertEqual(_await_descendants_gone(pids[0]), ())
            self.assertEqual(runtime.active_request_ids(), ())
            self.assertEqual(len(jobs), 1)
            self.assertTrue(jobs[0].closed)

    def test_request_id_is_reusable_after_setup_failure(self):
        """A leaked ``_active`` entry would make this second run fail."""
        with tempfile.TemporaryDirectory() as root_dir:
            runtime = _runtime(root_dir)
            _capture_jobs(windows_local_executor)
            request = _tree_request(root_dir, request_id="setup_fail_reuse")
            pids: list[tuple[int, ...]] = []

            def _gate() -> None:
                pids.append(_await_tree_pids(root_dir))

            with (
                _FailingThreadStart(fail_on_index=1, gate=_gate),
                self.assertRaises(RuntimeError),
            ):
                runtime.execute_with_receipt(request, now=datetime.now(timezone.utc))

            self.assertEqual(runtime.active_request_ids(), ())
            self.assertEqual(len(pids), 1)
            self.assertEqual(_await_descendants_gone(pids[0]), ())

    def test_normal_execution_still_returns_a_receipt_after_the_change(self):
        """The ordinary path must be unaffected: a short command still returns
        EXITED with its real output and no false cancellation."""
        with tempfile.TemporaryDirectory() as root_dir:
            runtime = _runtime(root_dir)
            _capture_jobs(windows_local_executor)
            request = LocalCommandRequest(
                request_id="setup_ok",
                run_id="run_3081_setup",
                device_id="device_3081_setup",
                root_ref="repo",
                argv=(str(Path(sys.executable).resolve()), "-c", "print('setup-ok-output')"),
                cwd_relative=".",
                requested_at=datetime.now(timezone.utc),
                timeout_seconds=60,
            )
            receipt = runtime.execute_with_receipt(request, now=datetime.now(timezone.utc))
            self.assertEqual(receipt.termination.value, "exited")
            self.assertEqual(receipt.result.exit_code, 0)
            self.assertFalse(receipt.result.cancelled)
            self.assertIn("setup-ok-output", receipt.result.stdout)
            self.assertEqual(runtime.active_request_ids(), ())

    def test_timeout_semantics_are_preserved_after_the_change(self):
        """Timeout must still terminate the tree and stay distinct from cancel."""
        with tempfile.TemporaryDirectory() as root_dir:
            runtime = _runtime(root_dir)
            _capture_jobs(windows_local_executor)
            request = LocalCommandRequest(
                request_id="setup_timeout",
                run_id="run_3081_setup",
                device_id="device_3081_setup",
                root_ref="repo",
                argv=(str(Path(sys.executable).resolve()), "-c", "import time; time.sleep(60)"),
                cwd_relative=".",
                requested_at=datetime.now(timezone.utc),
                timeout_seconds=1,
            )
            receipt = runtime.execute_with_receipt(request, now=datetime.now(timezone.utc))
            self.assertEqual(receipt.termination.value, "timed_out")
            self.assertFalse(receipt.result.cancelled)
            self.assertIsNone(receipt.result.exit_code)
            self.assertEqual(runtime.active_request_ids(), ())


if __name__ == "__main__":
    unittest.main()
