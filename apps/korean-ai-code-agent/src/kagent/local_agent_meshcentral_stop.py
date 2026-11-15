"""Stop one MeshCentral dispatch without importing the command port.

The command port re-exports these names for its existing callers. Keeping the stop
scripts and carrier here gives the dispatch-job module one dependency direction:
job primitives -> stop scripts/carrier -> command execution.
"""
from __future__ import annotations

import re
from typing import Any, Callable

from . import local_agent_mesh_command_phases as phases
from .local_agent_meshcentral_dispatch_job import dispatch_job_stop_ps


class MeshCentralCommandRefused(ValueError):
    """Bounded refusal of one command run. Never carries output or secrets."""


#: Every command leaves one file behind, named by its dispatch id and holding its pid.
PC_CANCEL_PID_FILE_PREFIX = "padiem-dispatch-"
_DISPATCH_ID = re.compile(r"^dsp_[0-9a-f]{16,64}$")
CANCEL_KILL_WAIT_SECONDS = 15
STOP_EVIDENCE = "__PADIEM_KILL__"


def _checked_dispatch_id(value: Any) -> str:
    if not isinstance(value, str) or _DISPATCH_ID.fullmatch(value) is None:
        raise MeshCentralCommandRefused("dispatch_id is not a dispatch identifier")
    return value


def _pid_file_literal(dispatch_id: str) -> str:
    """The PowerShell expression for this dispatch's own marker file on the PC."""
    return ("[IO.Path]::GetTempPath()+'" + PC_CANCEL_PID_FILE_PREFIX
            + _checked_dispatch_id(dispatch_id) + ".pid'")


#: A script and its credential line must fit before the terminal reader attaches.
TERMINAL_PREQUEUE_LIMIT_BYTES = 4096
TERMINAL_SCRIPT_BUDGET_BYTES = TERMINAL_PREQUEUE_LIMIT_BYTES - 256

#: Only LocalSystem or Administrators may author a marker that names a process to end.
TRUSTED_MARKER_SIDS = ("S-1-5-18", "S-1-5-32-544")
SWEEP_OWNER_SID_PS = (
    "function __padiemSid($p){try{"
    "(Get-Acl -LiteralPath $p).GetOwner"
    "([Security.Principal.SecurityIdentifier]).Value}catch{''}}"
)


def cancel_kill_command(dispatch_id: str, *, budget_bytes: int | None = None) -> str:
    """End exactly one stopped dispatch and its marker, preserving pid protections.

    The dispatch's named job is ended first so descendants survive no broken parent
    chain. Older dispatches have no job and continue through the original recorded-pid
    path. Marker ownership and start-time checks remain mandatory.
    """
    marker = "$__padiem_stop"
    checked = _checked_dispatch_id(dispatch_id)
    script = (
        "$ErrorActionPreference='SilentlyContinue';"
        + SWEEP_OWNER_SID_PS + ";"
        + dispatch_job_stop_ps(checked)
        + f"{marker}={_pid_file_literal(checked)};"
        f"if (Test-Path -LiteralPath {marker}) {{"
        "if ('" + "','".join(TRUSTED_MARKER_SIDS) + "' -contains (__padiemSid " + marker + ")) {"
        "$__padiem_v=@((Get-Content -LiteralPath " + marker + " | Select-Object -First 3));"
        "$__padiem_kill=[uint32]$__padiem_v[0];$__padiem_st=[string]$__padiem_v[2];"
        "if ($__padiem_kill) {"
        '$__padiem_r=Get-CimInstance Win32_Process -Filter "ProcessId=$__padiem_kill";'
        "if ($__padiem_r -and (-not $__padiem_st"
        " -or [string]$__padiem_r.CreationDate.ToFileTime() -eq $__padiem_st)) {"
        "& $env:SystemRoot\\System32\\taskkill.exe /T /F /PID $__padiem_kill | Out-Null } };"
        f"Remove-Item -LiteralPath {marker} -Force }} }};"
        "Write-Output ('__PADIEM_' + 'KILL__')"
    )
    budget = TERMINAL_SCRIPT_BUDGET_BYTES if budget_bytes is None else budget_bytes
    if len(script.encode("utf-8")) >= budget:
        raise MeshCentralCommandRefused(
            "the stop script exceeds the terminal prequeue budget"
        )
    return script


def cancel_job_command(dispatch_id: str, *, budget_bytes: int | None = None) -> str:
    """End this dispatch's job alone; old dispatches with no job change nothing."""
    script = (
        "$ErrorActionPreference='SilentlyContinue';"
        + dispatch_job_stop_ps(_checked_dispatch_id(dispatch_id))
        + "Write-Output ('__PADIEM_' + 'KILL__')"
    )
    budget = TERMINAL_SCRIPT_BUDGET_BYTES if budget_bytes is None else budget_bytes
    if len(script.encode("utf-8")) >= budget:
        raise MeshCentralCommandRefused(
            "the job stop script exceeds the terminal prequeue budget"
        )
    return script


def end_dispatch_job(
    self, *, node_ref: str, dispatch_id: str,
    phase_observer: Callable[[str], None] | None = None,
) -> bool:
    """Public command-port method that ends only this dispatch's named job."""
    def phase(name: str) -> None:
        if callable(phase_observer):
            try:
                phase_observer(name)
            except Exception:
                pass

    return self._end_dispatch_job(node_ref, _checked_dispatch_id(dispatch_id), phase)


def _end_dispatch_job(
    self, node_ref: str | None, dispatch_id: str, phase: Callable[[str], None],
) -> bool:
    """Best-effort command-port job stop, retaining the old no-job behavior."""
    if node_ref is None:
        return False
    try:
        raw = self._run_shell_session(
            node_ref, cancel_job_command(dispatch_id),
            answer=lambda buf: STOP_EVIDENCE.encode("ascii") in buf,
            wait_seconds=CANCEL_KILL_WAIT_SECONDS,
        )
    except Exception:
        phase(phases.CANCEL_KILL_REFUSED)
        return False
    if STOP_EVIDENCE.encode("ascii") not in (raw or b""):
        phase(phases.CANCEL_KILL_UNVERIFIED)
        return False
    phase(phases.CANCEL_KILL)
    return True
