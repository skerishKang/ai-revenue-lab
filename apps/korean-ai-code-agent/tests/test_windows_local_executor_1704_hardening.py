from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from kagent.contracts import ContractError
from kagent.local_agent import LocalAgentDeviceProfile, LocalAgentPlatform, LocalCommandRequest, LocalRoot
from kagent.windows_local_executor import (
    DeterministicWorktreeStatePort,
    WindowsExecutableProfile,
    WindowsSubprocessLocalAgentRuntime,
    _contained_working_directory,
    _require_request_not_future,
)


BASE = datetime(2026, 9, 4, 3, 0, tzinfo=timezone.utc)


def _request(*, executable: str, requested_at: datetime) -> LocalCommandRequest:
    return LocalCommandRequest(
        request_id="request_1704_hardening",
        run_id="run_1704_hardening",
        device_id="device_1704_hardening",
        root_ref="repo",
        argv=(executable, "-V"),
        cwd_relative=".",
        requested_at=requested_at,
        timeout_seconds=10,
    )


class _RecordingAuthorization:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def authorize(self, *, request, profile, now):
        del profile, now
        self.calls.append(request.request_id)
        raise AssertionError("future-dated request reached authorization")


class WindowsLocalExecutor1704TimeGateTests(unittest.TestCase):
    def test_future_dated_request_gate_is_cross_platform_and_exact_now_is_allowed(self) -> None:
        request = _request(executable=r"C:\Tools\tool.exe", requested_at=BASE + timedelta(seconds=1))
        with self.assertRaisesRegex(ContractError, "future-dated"):
            _require_request_not_future(request, now=BASE)

        exact = _request(executable=r"C:\Tools\tool.exe", requested_at=BASE)
        _require_request_not_future(exact, now=BASE)

    @unittest.skipUnless(os.name == "nt", "real executor authorization order is Windows-first")
    def test_future_dated_request_fails_before_authorization_or_process_creation(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            executable = str(Path(sys.executable).resolve())
            authorization = _RecordingAuthorization()
            runtime = WindowsSubprocessLocalAgentRuntime(
                device=LocalAgentDeviceProfile(
                    device_id="device_1704_hardening",
                    workspace_ref="workspace_1704_hardening",
                    platform=LocalAgentPlatform.WINDOWS,
                    roots=(LocalRoot(root_ref="repo", windows_path=root_dir),),
                ),
                executable_profiles=(
                    WindowsExecutableProfile(
                        profile_ref="python_1704_hardening",
                        executable_path=executable,
                    ),
                ),
                authorization_port=authorization,
                worktree_state_port=DeterministicWorktreeStatePort(),
            )
            request = _request(executable=executable, requested_at=BASE + timedelta(seconds=1))
            with self.assertRaisesRegex(ContractError, "future-dated"):
                runtime.execute_with_receipt(request, now=BASE)
            self.assertEqual(authorization.calls, [])
            self.assertEqual(runtime.active_request_ids(), ())


@unittest.skipUnless(os.name == "nt", "NTFS junction/reparse evidence requires Windows")
class WindowsLocalExecutor1704ReparseTests(unittest.TestCase):
    def test_windows_junction_escape_outside_selected_root_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir, tempfile.TemporaryDirectory() as outside_dir:
            outside = Path(outside_dir).resolve()
            sentinel = outside / "outside-sentinel.txt"
            sentinel.write_text("must remain outside", encoding="utf-8")
            junction = Path(root_dir) / "escape-junction"
            created = subprocess.run(
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(outside)],
                check=False,
                capture_output=True,
                text=True,
                shell=False,
            )
            self.assertEqual(
                created.returncode,
                0,
                msg=f"failed to create Windows junction fixture: {created.stderr or created.stdout}",
            )
            try:
                with self.assertRaisesRegex(ContractError, "escapes the selected root"):
                    _contained_working_directory(root_dir, "escape-junction")
                self.assertTrue(sentinel.exists())
            finally:
                if junction.exists():
                    os.rmdir(junction)


if __name__ == "__main__":
    unittest.main()
