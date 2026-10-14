"""Supervise the one existing Windows Resident/Local Runner (#4139 §2/§5).

Claw Connect does **not** carry a second executor. It supervises the process
that already exists in this repository:

    ``apps/korean-ai-code-agent/src/kagent/local_agent_resident_process.py``

The supervisor owns start, stop, restart and process-tree cleanup, so Quit
leaves no orphan process behind on the PC. The Resident's own authority,
Broker one-shot consumption, P01 approval and pairing rules are unchanged —
this module only starts, watches and stops that process.

The command is injected so the offline tests never launch the real Resident.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence

#: Grace period (seconds) between a graceful stop and the forced kill.
TERMINATE_GRACE_SECONDS = 8.0
#: The one repository entry point Connect supervises. No second runner.
RESIDENT_ENTRY_MODULE = "kagent.local_agent_resident_process"


def default_resident_command(
    *, python: str | None = None, src_root: str | None = None
) -> list[str]:
    """The canonical command that starts the existing Resident process.

    ``src_root`` is the repository's ``apps/korean-ai-code-agent/src``; it is
    supplied by the installer or the developer checkout, never guessed from a
    remote source.
    """
    interpreter = python or sys.executable
    command = [interpreter, "-m", RESIDENT_ENTRY_MODULE]
    if src_root:
        command = [interpreter, "-c", f"import sys; sys.path.insert(0, {src_root!r}); "
                  f"from {RESIDENT_ENTRY_MODULE} import main; sys.exit(main(sys.argv[1:]))"]
    return command


class ResidentProcess:
    """Handle to the supervised Resident child process."""

    def __init__(self, process: subprocess.Popen[bytes] | None) -> None:
        self._process = process

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process is not None else None

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def returncode(self) -> int | None:
        return self._process.returncode if self._process is not None else None

    def terminate(self, grace: float = TERMINATE_GRACE_SECONDS) -> int | None:
        """Graceful stop, then force kill. Always reaps the process."""
        process = self._process
        if process is None or process.poll() is not None:
            return process.returncode if process is not None else None
        try:
            process.terminate()
        except OSError:
            pass
        try:
            return process.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            pass
        try:
            process.kill()
        except OSError:
            pass
        try:
            return process.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            return None


class ResidentSupervisor:
    """Single supervised Resident per Connect process (no second runner)."""

    def __init__(
        self,
        command: Sequence[str],
        *,
        popen: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
        env: Mapping[str, str] | Callable[[], Mapping[str, str] | None] | None = None,
    ) -> None:
        if not command:
            raise ValueError("resident command must not be empty")
        self._command = list(command)
        self._popen = popen
        # ``env`` may be a provider so a restart resolves the *current*
        # committed enrollment instead of a snapshot taken at construction.
        self._env = env if callable(env) else (dict(env) if env is not None else None)
        self._resident: ResidentProcess | None = None

    def _resolved_env(self) -> dict[str, str] | None:
        provider = self._env
        if provider is None:
            return None
        resolved = provider() if callable(provider) else provider
        return dict(resolved) if resolved is not None else None

    @property
    def command(self) -> list[str]:
        return list(self._command)

    @property
    def resident(self) -> ResidentProcess | None:
        return self._resident

    def is_running(self) -> bool:
        return self._resident is not None and self._resident.running

    def start(self) -> ResidentProcess:
        """Start the existing Resident. Refuses if one is already running."""
        if self.is_running():
            return self._resident  # type: ignore[return-value]
        env = self._resolved_env()
        if env is None:
            process = self._popen(
                self._command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            process = self._popen(
                self._command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, env=env,
            )
        self._resident = ResidentProcess(process)
        return self._resident

    def stop(self, grace: float = TERMINATE_GRACE_SECONDS) -> int | None:
        """Stop the supervised Resident and reap it (no orphan left behind)."""
        resident, self._resident = self._resident, None
        if resident is None:
            return None
        return resident.terminate(grace=grace)

    def restart(self, grace: float = TERMINATE_GRACE_SECONDS) -> ResidentProcess:
        self.stop(grace=grace)
        return self.start()

    def wait_idle(self, timeout: float = 15.0, poll: float = 0.05) -> bool:
        """Wait until the supervised child is gone. True when nothing remains."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._resident is None or not self._resident.running:
                return True
            time.sleep(poll)
        return self._resident is None or not self._resident.running


__all__ = [
    "RESIDENT_ENTRY_MODULE",
    "TERMINATE_GRACE_SECONDS",
    "ResidentProcess",
    "ResidentSupervisor",
    "default_resident_command",
]
