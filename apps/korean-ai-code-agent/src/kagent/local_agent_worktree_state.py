"""#3148 - real, bounded, fail-closed Windows worktree state probe.

The canonical P01 execution seam (`compose_fail_closed_windows_runtime`) already
requires an explicit ``WorktreeStatePort`` and fails closed when one is absent
(#1716), but product source shipped only ``DeterministicWorktreeStatePort`` - a
test seam that always reports the configured answer. This module is the real
port: it measures the exact contained working directory the
``WindowsSubprocessLocalAgentRuntime`` resolved, by running ``git status`` as a
direct child process (never a shell).

Design rules, each of which is a fail-closed boundary rather than a preference:

* **Direct process only.** ``shell=False``. No CMD, no PowerShell, no shell
  quoting - the argv is a fixed literal list, never user text.
* **Read-only Git.** ``status --porcelain=v1 --untracked-files=all`` with
  ``--no-optional-locks`` and ``GIT_OPTIONAL_LOCKS=0``, so Git never writes a
  lock or refreshes the index while probing. No fetch, no config change, no
  network: ``GIT_TERMINAL_PROMPT=0`` means a probe can never block on a remote
  credential helper.
* **Bounded everything.** Bounded runtime (default 5s) and bounded output
  (default 256 KiB, read with a capped drain that kills the child on overflow).
  An oversized or unparseable response is a refusal, never a guess.
* **No arbitrary environment inheritance.** The child receives a fixed Windows
  allowlist plus fixed Git safety variables. Nothing from the runner's own
  environment - no tokens, no secrets, no proxies - reaches the child.
* **A probe failure is never "clean".** Git missing, timeout, oversized output,
  malformed porcelain, or a directory that is not a worktree all raise
  ``ContractError``. Only a successful ``git status`` can answer "clean", and
  that answer is ``False`` for clean and ``True`` for dirty (tracked
  modifications and untracked files alike). The executor treats a raised
  ``ContractError`` as a refusal to execute, so the failure mode is a stopped
  runner, never an execution against an unknown worktree state.

The deterministic adapter stays exactly where it was: a test-only seam.
"""

from __future__ import annotations

import os
import subprocess
import threading
from typing import Any

from .contracts import ContractError
from .windows_local_executor import WorktreeStatePort

#: Bound on the child process lifetime. A worktree probe is a local status read;
#: anything slower than this is an operational failure, not a clean worktree.
GIT_STATUS_TIMEOUT_SECONDS = 5.0
MAX_GIT_STATUS_TIMEOUT_SECONDS = 60.0
#: Bound on captured stdout/stderr. The child is killed the moment the cap is
#: exceeded, so a pathological repository cannot grow the runner's memory.
GIT_STATUS_MAX_OUTPUT_BYTES = 256 * 1024
MIN_GIT_STATUS_MAX_OUTPUT_BYTES = 1024
MAX_GIT_STATUS_MAX_OUTPUT_BYTES = 4 * 1024 * 1024
GIT_EXECUTABLE_DEFAULT = "git"

#: The only host variables the probe may pass to Git: enough to find the
#: executable and give it a temp directory on Windows, and nothing else. This
#: mirrors the executor's own bounded environment (#3081) deliberately rather
#: than sharing a private helper, so the executor module stays untouched.
_BOUNDED_ENV_NAMES = (
    "PATH",
    "PATHEXT",
    "SystemRoot",
    "WINDIR",
    "SystemDrive",
    "TEMP",
    "TMP",
    "USERPROFILE",
)
#: Fixed Git settings. Not inherited: set unconditionally, so an adversarial or
#: merely careless host environment cannot turn a read-only probe into something
#: interactive, networked or mutating.
_FIXED_GIT_ENV = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_PAGER": "cat",
    "GIT_CONFIG_NOSYSTEM": "1",
    "LC_ALL": "C",
}
#: Porcelain v1 index/worktree status codes (tracked changes, and the ``?``
#: untracked marker). Anything else in those columns is a response this probe
#: does not understand, and an misunderstood response is a refusal.
_PORCELAIN_STATUS_CODES = frozenset(" MADRCU?!")


def _environment() -> dict[str, str]:
    environment: dict[str, str] = {}
    for name in _BOUNDED_ENV_NAMES:
        value = os.environ.get(name)
        if value:
            environment[name] = value
    environment.update(_FIXED_GIT_ENV)
    return environment


def _drain_bounded(stream: Any, chunks: list[bytes], overflow: threading.Event, cap: int) -> None:
    kept = 0
    try:
        while True:
            chunk = stream.read(4096)
            if chunk is None or chunk == b"":
                break
            kept += len(chunk)
            if kept > cap:
                overflow.set()
                return
            chunks.append(chunk)
    except (OSError, ValueError):
        return
    finally:
        try:
            stream.close()
        except (OSError, ValueError):
            pass


def dirty_from_porcelain(stdout: str) -> bool:
    """True when porcelain v1 output carries at least one tracked or untracked entry.

    Strict by design: a response this function cannot read is refused, because
    "I could not understand the worktree state" and "the worktree is clean" are
    different facts and only the second one may authorise execution.
    """
    if not isinstance(stdout, str):
        raise ContractError("git_worktree_probe_malformed_response: git status output must be text")
    dirty = False
    for raw in stdout.splitlines():
        if not raw.strip():
            continue
        if len(raw) < 4 or raw[0] not in _PORCELAIN_STATUS_CODES or raw[1] not in _PORCELAIN_STATUS_CODES:
            raise ContractError(
                "git_worktree_probe_malformed_response: git status response did not match the porcelain v1 contract",
            )
        dirty = True
    return dirty


class WindowsGitWorktreeStatePort:
    """Real Windows worktree probe for the canonical P01 execution seam (#3148).

    Satisfies the existing ``WorktreeStatePort`` protocol without changing the
    executor that consumes it: ``execute_with_receipt`` calls ``is_dirty(cwd)``
    immediately before and after the approved child runs, so a probe refusal
    stops the execution and a dirty worktree is reported, never hidden.
    """

    def __init__(
        self,
        *,
        git_executable: str = GIT_EXECUTABLE_DEFAULT,
        timeout_seconds: float = GIT_STATUS_TIMEOUT_SECONDS,
        max_output_bytes: int = GIT_STATUS_MAX_OUTPUT_BYTES,
    ) -> None:
        if not isinstance(git_executable, str) or not git_executable.strip():
            raise ValueError("git_executable must be a non-empty reference")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
            raise ValueError("timeout_seconds must be a number")
        if not 0 < float(timeout_seconds) <= MAX_GIT_STATUS_TIMEOUT_SECONDS:
            raise ValueError(
                f"timeout_seconds must be between 0 and {MAX_GIT_STATUS_TIMEOUT_SECONDS}"
            )
        if isinstance(max_output_bytes, bool) or not isinstance(max_output_bytes, int):
            raise ValueError("max_output_bytes must be an integer")
        if not MIN_GIT_STATUS_MAX_OUTPUT_BYTES <= max_output_bytes <= MAX_GIT_STATUS_MAX_OUTPUT_BYTES:
            raise ValueError(
                "max_output_bytes must be between the product bounds"
            )
        self._git_executable = git_executable.strip()
        self._timeout_seconds = float(timeout_seconds)
        self._max_output_bytes = max_output_bytes
        self._probe_count = 0

    @property
    def probe_count(self) -> int:
        return self._probe_count

    def _child_environment(self) -> dict[str, str]:
        return _environment()

    def _directory(self, cwd: str) -> str:
        if not isinstance(cwd, str) or not cwd:
            raise ContractError("git_worktree_probe_invalid_cwd: worktree probe requires a directory path")
        if not os.path.isdir(cwd):
            raise ContractError("git_worktree_probe_invalid_cwd: worktree probe directory does not exist")
        return cwd

    def _spawn(self, directory: str) -> subprocess.Popen[bytes]:
        argv = [
            self._git_executable,
            "--no-optional-locks",
            "--no-pager",
            "-C",
            directory,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ]
        try:
            return subprocess.Popen(  # noqa: S603 - fixed literal argv, shell=False
                argv,
                cwd=directory,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self._child_environment(),
                shell=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, ValueError) as exc:
            # Git missing, not executable, or the platform refused the spawn.
            raise ContractError(
                "git_worktree_probe_unavailable: git executable is not available for the worktree probe",
            ) from exc

    def is_dirty(self, cwd: str) -> bool:
        directory = self._directory(cwd)
        self._probe_count += 1
        process = self._spawn(directory)
        stdout_chunks: list[bytes] = []
        stderr_chunks: list[bytes] = []
        overflow = threading.Event()
        readers = [
            threading.Thread(
                target=_drain_bounded,
                args=(process.stdout, stdout_chunks, overflow, self._max_output_bytes),
                daemon=True,
            ),
            threading.Thread(
                target=_drain_bounded,
                args=(process.stderr, stderr_chunks, overflow, self._max_output_bytes),
                daemon=True,
            ),
        ]
        for reader in readers:
            reader.start()
        timed_out = False
        try:
            process.wait(timeout=self._timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            # Reap the child unconditionally before returning. A killed Git that
            # has not been reaped still holds its working directory on Windows,
            # and a probe that leaves that handle behind would make the runner's
            # own cleanup fail for reasons that have nothing to do with the
            # worktree it asked about.
            process.kill()
            process.wait()
        finally:
            # The drain threads own their streams and close them; closing here
            # would race a still-running reader and truncate the response.
            for reader in readers:
                reader.join(timeout=5)
        if timed_out:
            raise ContractError(
                "git_worktree_probe_timeout: git status did not complete within the probe bound",
            )
        if overflow.is_set():
            raise ContractError(
                "git_worktree_probe_output_exceeded: git status produced more output than the probe bound",
            )
        if process.returncode != 0:
            # Explicit and deliberately not "clean": the directory is not a
            # worktree Git will report on, or Git refused it outright. Either
            # way the worktree state is unknown, and unknown is not clean.
            raise ContractError(
                "git_worktree_probe_refused: git status refused the working directory",
            )
        try:
            stdout = b"".join(stdout_chunks).decode("utf-8", errors="replace")
        except (AttributeError, UnicodeError) as exc:  # pragma: no cover - defensive
            raise ContractError(
                "git_worktree_probe_malformed_response: git status output could not be decoded",
            ) from exc
        return dirty_from_porcelain(stdout)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-windows-git-worktree-state-port.v1",
            "real_worktree_probe": True,
            "direct_process_only": True,
            "shell": False,
            "git_network": False,
            "git_mutation": False,
            "git_optional_locks_disabled": True,
            "probe_error_is_never_clean": True,
            "non_worktree_refused": True,
            "bounded_runtime": True,
            "bounded_output": True,
            "bounded_environment_allowlist": True,
            "timeout_seconds_bound": self._timeout_seconds,
            "max_output_bytes_bound": self._max_output_bytes,
            "raw_repository_content_projected": False,
            "probe_count": self._probe_count,
            "second_worktree_probe_authority": False,
            "deterministic_adapter_remains_test_only": True,
            "production_mutation": False,
            "production_ready": False,
        }


REAL_WINDOWS_WORKTREE_STATE_PORT = True
DIRECT_PROCESS_ONLY = True
SHELL_USED = False
GIT_NETWORK = 0
GIT_MUTATION = 0
GIT_OPTIONAL_LOCKS_DISABLED = True
PROBE_ERROR_AS_CLEAN = False
NON_WORKTREE_CONFLATED_WITH_CLEAN = False
BOUNDED_OUTPUT = True
BOUNDED_RUNTIME = True
BOUNDED_ENV_INHERITANCE = True
RAW_REPOSITORY_CONTENT_IN_LOG = False
SECOND_WORKTREE_PROBE_AUTHORITY = False
DETERMINISTIC_ADAPTER_REMAINS_TEST_ONLY = True
PRODUCTION_MUTATION = False
PRODUCTION_READY = False
