"""#3148 - real Windows worktree probe evidence.

Every scenario runs the real ``git`` binary against a real temporary
repository: there is no stubbed Git, no mocked process, and no fabricated
porcelain output except in the parser unit test, which tests the parser and
claims nothing about a process.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from padiem_ai_core.agent_approval import (
    ApprovalOutcome,
    ApprovalPause,
    ApprovalRequirement,
    VerifiedApprovalDecision,
    tool_invocation_digest,
)

from kagent.contracts import ContractError
from kagent.local_agent import (
    LocalAgentDeviceProfile,
    LocalAgentPlatform,
    LocalCommandRequest,
    LocalRoot,
)
from kagent.local_agent_permissions import (
    LocalCapability,
    LocalPermissionRequest,
    default_device_permission_profile,
)
from kagent.local_agent_management import compose_fail_closed_windows_runtime
from kagent.local_agent_worktree_state import (
    BOUNDED_ENV_INHERITANCE,
    BOUNDED_OUTPUT,
    DIRECT_PROCESS_ONLY,
    GIT_MUTATION,
    GIT_NETWORK,
    PROBE_ERROR_AS_CLEAN,
    RAW_REPOSITORY_CONTENT_IN_LOG,
    REAL_WINDOWS_WORKTREE_STATE_PORT,
    SHELL_USED,
    WindowsGitWorktreeStatePort,
    dirty_from_porcelain,
)
from kagent.windows_execution_authorization import (
    DeterministicWindowsExecutionAuthorityEvidencePort,
    P01LocalPermissionWindowsExecutionAuthorizationPort,
    WindowsExecutionAuthorityEvidence,
    windows_execution_tool_invocation,
)
from kagent.windows_local_executor import (
    WindowsExecutableProfile,
    WindowsSubprocessLocalAgentRuntime,
    command_request_fingerprint,
)

NOW = datetime(2026, 9, 27, 14, 0, tzinfo=timezone.utc)


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


class _TempRepo:
    """A real temporary Git worktree (real `git init`, real commit)."""

    def __init__(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.path = Path(self._temp.name) / "repo"
        self.path.mkdir()
        _git("init", "--initial-branch=main", cwd=self.path)
        _git("config", "user.email", "probe@example.invalid", cwd=self.path)
        _git("config", "user.name", "Probe", cwd=self.path)
        (self.path / "tracked.txt").write_text("clean\n", encoding="utf-8")
        _git("add", "tracked.txt", cwd=self.path)
        _git("commit", "-m", "initial", cwd=self.path)

    def dirty_tracked(self) -> None:
        (self.path / "tracked.txt").write_text("modified\n", encoding="utf-8")

    def add_untracked(self, name: str = "untracked.txt", size: int = 0) -> None:
        (self.path / name).write_text("x" * size, encoding="utf-8")

    def close(self) -> None:
        self._temp.cleanup()


class _TempDir:
    def __init__(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.path = Path(self._temp.name)

    def close(self) -> None:
        self._temp.cleanup()


class RealWindowsWorktreeStatePortTests(unittest.TestCase):
    def setUp(self) -> None:
        self._repo = _TempRepo()
        self.addCleanup(self._repo.close)

    # -- the five required real-Windows scenarios ---------------------------

    def test_clean_worktree_is_reported_clean(self) -> None:
        port = WindowsGitWorktreeStatePort()
        self.assertFalse(port.is_dirty(str(self._repo.path)))
        self.assertEqual(port.probe_count, 1)

    def test_tracked_modification_is_reported_dirty(self) -> None:
        self._repo.dirty_tracked()
        port = WindowsGitWorktreeStatePort()
        self.assertTrue(port.is_dirty(str(self._repo.path)))

    def test_untracked_file_is_reported_dirty(self) -> None:
        self._repo.add_untracked()
        port = WindowsGitWorktreeStatePort()
        self.assertTrue(port.is_dirty(str(self._repo.path)))

    def test_deleted_tracked_file_is_reported_dirty(self) -> None:
        (self._repo.path / "tracked.txt").unlink()
        port = WindowsGitWorktreeStatePort()
        self.assertTrue(port.is_dirty(str(self._repo.path)))

    def test_non_worktree_directory_is_refused_not_clean(self) -> None:
        # Explicit behaviour: a directory Git will not report on is *unknown*,
        # and unknown must never be silently answered as "clean".
        outside = _TempDir()
        self.addCleanup(outside.close)
        port = WindowsGitWorktreeStatePort()
        with self.assertRaises(ContractError) as refused:
            port.is_dirty(str(outside.path))
        self.assertTrue(str(refused.exception).startswith("git_worktree_probe_refused"), str(refused.exception))
        self.assertFalse(str(refused.exception).startswith("git_worktree_probe_unavailable"))

    # -- fail-closed operational failures ------------------------------------

    def test_missing_git_fails_closed(self) -> None:
        port = WindowsGitWorktreeStatePort(git_executable=r"C:\nonexistent-dir\git.exe")
        with self.assertRaises(ContractError) as refused:
            port.is_dirty(str(self._repo.path))
        self.assertTrue(str(refused.exception).startswith("git_worktree_probe_unavailable"), str(refused.exception))
        # Real `git`, real child process, killed by the real bound.
        port = WindowsGitWorktreeStatePort(timeout_seconds=0.001)
        with self.assertRaises(ContractError) as refused:
            port.is_dirty(str(self._repo.path))
        self.assertTrue(str(refused.exception).startswith("git_worktree_probe_timeout"), str(refused.exception))
        # Real porcelain output above the bound: the cap refuses rather than
        # buffering an unbounded response.
        for index in range(80):
            self._repo.add_untracked(f"untracked_{index:03d}_" + "n" * 40)
        port = WindowsGitWorktreeStatePort(max_output_bytes=1024)
        with self.assertRaises(ContractError) as refused:
            port.is_dirty(str(self._repo.path))
        self.assertTrue(str(refused.exception).startswith("git_worktree_probe_output_exceeded"), str(refused.exception))
        port = WindowsGitWorktreeStatePort()
        with self.assertRaises(ContractError) as refused:
            port.is_dirty(str(self._repo.path / "missing"))
        self.assertTrue(str(refused.exception).startswith("git_worktree_probe_invalid_cwd"), str(refused.exception))
        for response in ("??", "nonsense line", "\x1b[31mM  file.txt\x1b[0m", "M"):
            with self.assertRaises(ContractError) as refused:
                dirty_from_porcelain(response)
            self.assertTrue(str(refused.exception).startswith("git_worktree_probe_malformed_response"), str(refused.exception))
        self.assertFalse(dirty_from_porcelain(""))
        self.assertFalse(dirty_from_porcelain("\n\n"))
        self.assertTrue(dirty_from_porcelain(" M tracked.txt\n"))
        self.assertTrue(dirty_from_porcelain("?? untracked.txt\n"))
        self.assertTrue(dirty_from_porcelain("R  old.txt -> new.txt\n"))

    # -- bounded environment, no inherited secrets --------------------------

    def test_probe_timeout_fails_closed(self) -> None:
        # Real `git`, real child process, killed by the real bound.
        port = WindowsGitWorktreeStatePort(timeout_seconds=0.001)
        with self.assertRaises(ContractError) as refused:
            port.is_dirty(str(self._repo.path))
        self.assertTrue(str(refused.exception).startswith("git_worktree_probe_timeout"), str(refused.exception))

    def test_oversized_output_fails_closed(self) -> None:
        # Real porcelain output above the bound: the cap refuses rather than
        # buffering an unbounded response.
        for index in range(80):
            self._repo.add_untracked(f"untracked_{index:03d}_" + "n" * 40)
        port = WindowsGitWorktreeStatePort(max_output_bytes=1024)
        with self.assertRaises(ContractError) as refused:
            port.is_dirty(str(self._repo.path))
        self.assertTrue(
            str(refused.exception).startswith("git_worktree_probe_output_exceeded"), str(refused.exception)
        )

    def test_invalid_cwd_fails_closed(self) -> None:
        port = WindowsGitWorktreeStatePort()
        with self.assertRaises(ContractError) as refused:
            port.is_dirty(str(self._repo.path / "missing"))
        self.assertTrue(str(refused.exception).startswith("git_worktree_probe_invalid_cwd"), str(refused.exception))

    def test_malformed_porcelain_is_refused_not_clean(self) -> None:
        for response in ("??", "nonsense line", "\x1b[31mM  file.txt\x1b[0m", "M"):
            with self.assertRaises(ContractError) as refused:
                dirty_from_porcelain(response)
            self.assertTrue(
                str(refused.exception).startswith("git_worktree_probe_malformed_response"), str(refused.exception)
            )

    def test_porcelain_parser_reads_both_directions(self) -> None:
        self.assertFalse(dirty_from_porcelain(""))
        self.assertFalse(dirty_from_porcelain("\n\n"))
        self.assertTrue(dirty_from_porcelain(" M tracked.txt\n"))
        self.assertTrue(dirty_from_porcelain("?? untracked.txt\n"))
        self.assertTrue(dirty_from_porcelain("R  old.txt -> new.txt\n"))

    def test_child_environment_is_a_fixed_allowlist(self) -> None:
        canary = "GATE_PROBE_SECRET_CANARY_VALUE"
        previous = os.environ.get(canary)
        os.environ[canary] = "leaked-if-inherited"
        self.addCleanup(lambda: os.environ.__setitem__(canary, previous) if previous else os.environ.pop(canary, None))
        port = WindowsGitWorktreeStatePort()
        environment = port._child_environment()
        self.assertNotIn(canary, environment)
        self.assertEqual(environment["GIT_TERMINAL_PROMPT"], "0")
        self.assertEqual(environment["GIT_OPTIONAL_LOCKS"], "0")
        self.assertTrue(set(environment) - {
            "GIT_TERMINAL_PROMPT",
            "GIT_OPTIONAL_LOCKS",
            "GIT_PAGER",
            "GIT_CONFIG_NOSYSTEM",
            "LC_ALL",
        } <= {
            "PATH", "PATHEXT", "SystemRoot", "WINDIR", "SystemDrive", "TEMP", "TMP", "USERPROFILE",
        })

    def test_probe_does_not_mutate_the_repository(self) -> None:
        before = _git("status", "--porcelain=v1", "--untracked-files=all", cwd=self._repo.path).stdout
        ref_before = _git("rev-parse", "HEAD", cwd=self._repo.path).stdout
        WindowsGitWorktreeStatePort().is_dirty(str(self._repo.path))
        after = _git("status", "--porcelain=v1", "--untracked-files=all", cwd=self._repo.path).stdout
        ref_after = _git("rev-parse", "HEAD", cwd=self._repo.path).stdout
        self.assertEqual(before, after)
        self.assertEqual(ref_before, ref_after)

    # -- source-truth constants ---------------------------------------------

    def test_source_truth_constants(self) -> None:
        self.assertTrue(REAL_WINDOWS_WORKTREE_STATE_PORT)
        self.assertTrue(DIRECT_PROCESS_ONLY)
        self.assertFalse(SHELL_USED)
        self.assertEqual(GIT_NETWORK, 0)
        self.assertEqual(GIT_MUTATION, 0)
        self.assertFalse(PROBE_ERROR_AS_CLEAN)
        self.assertTrue(BOUNDED_OUTPUT)
        self.assertTrue(BOUNDED_ENV_INHERITANCE)
        self.assertFalse(RAW_REPOSITORY_CONTENT_IN_LOG)

    def test_probe_source_never_uses_a_shell(self) -> None:
        source = Path(__file__).parents[1] / "src" / "kagent" / "local_agent_worktree_state.py"
        text = source.read_text(encoding="utf-8")
        self.assertIn("shell=False", text)
        self.assertNotIn("shell=True", text)
        for blocked in ("cmd.exe", "powershell", "os.system", "shell=True"):
            self.assertNotIn(blocked, text)


def _approved_port_permission(
    *, run_id: str, device_id: str, capability: LocalCapability, target_ref: str, root_ref: str | None
) -> LocalPermissionRequest:
    return LocalPermissionRequest(
        action_id="permission_probe",
        run_id=run_id,
        device_id=device_id,
        capability=capability,
        target_ref=target_ref,
        root_ref=root_ref,
    )


class CanonicalRuntimeCompositionWithRealProbeTests(unittest.TestCase):
    """The real probe inside the canonical fail-closed P01 composition."""

    def _device(self, root: Path) -> LocalAgentDeviceProfile:
        return LocalAgentDeviceProfile(
            device_id="device_1",
            workspace_ref="workspace_1",
            platform=LocalAgentPlatform.WINDOWS,
            roots=(LocalRoot(root_ref="repo", windows_path=str(root)),),
        )

    def _profile(self) -> WindowsExecutableProfile:
        return WindowsExecutableProfile(
            profile_ref="python",
            executable_path=sys.executable,
            required_capabilities=("process.execute",),
            may_access_network=False,
        )

    def _evidence(self, request: LocalCommandRequest, profile: WindowsExecutableProfile):
        invocation = windows_execution_tool_invocation(request, profile)
        pause = ApprovalPause(
            pause_id="pause_probe",
            run_id=request.run_id,
            agent_runtime_id="agent_probe",
            tool_id=invocation.tool_id,
            invocation_sha256=tool_invocation_digest(invocation),
            requirement=ApprovalRequirement.USER_CONFIRMATION,
            step_index=1,
            created_at=NOW - timedelta(minutes=2),
            expires_at=NOW + timedelta(minutes=10),
            approval_scope=profile.required_capabilities,
        )
        decision = VerifiedApprovalDecision(
            decision_id="decision_probe",
            pause_id="pause_probe",
            outcome=ApprovalOutcome.APPROVED,
            authority_ref="p01_authority_probe",
            evidence_ref="p01_evidence_probe",
            decided_at=NOW - timedelta(seconds=30),
        )
        fingerprint = command_request_fingerprint(request)
        return WindowsExecutionAuthorityEvidence(
            evidence_ref="authority_evidence_probe",
            request_fingerprint=fingerprint,
            permission_requests=(
                _approved_port_permission(
                    run_id=request.run_id,
                    device_id=request.device_id,
                    capability=LocalCapability.PROCESS_EXECUTE,
                    target_ref=fingerprint,
                    root_ref=request.root_ref,
                ),
            ),
            approval_pause=pause,
            approval_decision=decision,
            local_policy_ref="local_policy_probe",
            expires_at=NOW + timedelta(minutes=5),
        )

    def _runtime(self, repo: Path, port) -> WindowsSubprocessLocalAgentRuntime:
        device = self._device(repo)
        permission_profile = default_device_permission_profile(device=device)
        request = LocalCommandRequest(
            request_id="request_probe",
            run_id="run_probe",
            device_id="device_1",
            root_ref="repo",
            argv=(sys.executable, "-c", "open('touched.txt', 'w').write('x')"),
            cwd_relative=".",
            requested_at=NOW - timedelta(seconds=1),
            timeout_seconds=30,
        )
        profile = self._profile()
        evidence = self._evidence(request, profile)
        return compose_fail_closed_windows_runtime(
            device=device,
            executable_profiles=(profile,),
            authorization_port=P01LocalPermissionWindowsExecutionAuthorizationPort(
                permission_profile=permission_profile,
                evidence_port=DeterministicWindowsExecutionAuthorityEvidencePort((evidence,)),
            ),
            worktree_state_port=port,
        ), request

    def test_approved_execution_runs_and_the_real_probe_sees_the_result(self) -> None:
        repo = _TempRepo()
        self.addCleanup(repo.close)
        port = WindowsGitWorktreeStatePort()
        runtime, request = self._runtime(repo.path, port)
        self.assertIsInstance(runtime, WindowsSubprocessLocalAgentRuntime)

        # The canonical runtime measures the worktree immediately before and
        # after the approved child, using the real probe.
        receipt = runtime.execute(request, now=NOW)
        self.assertEqual(receipt.exit_code, 0)
        self.assertTrue((repo.path / "touched.txt").exists())
        self.assertEqual(port.probe_count, 2, "executor probes before and after execution")
        # The approved child created an untracked file: the real probe sees it.
        self.assertTrue(port.is_dirty(str(repo.path)))

    def test_probe_failure_stops_an_approved_execution_without_side_effect(self) -> None:
        repo = _TempRepo()
        self.addCleanup(repo.close)
        broken = WindowsGitWorktreeStatePort(git_executable=r"C:\nonexistent-dir\git.exe")
        runtime, request = self._runtime(repo.path, broken)
        with self.assertRaises(ContractError) as refused:
            runtime.execute(request, now=NOW)
        self.assertTrue(str(refused.exception).startswith("git_worktree_probe_unavailable"), str(refused.exception))
        self.assertFalse((repo.path / "touched.txt").exists())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
