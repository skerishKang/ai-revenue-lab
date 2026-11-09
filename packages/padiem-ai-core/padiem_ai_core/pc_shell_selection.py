"""#7188 R4 ② — the one table both PC command lanes resolve shell names through.

Before this module a shell name was interpreted in three places: the chat
tool's whitelist (``PC_SHELL_SHELLS`` in ``mcp_gateway_shell``), the SYSTEM
dispatcher script's ``$env:PADIEM_MCP_SHELL`` if/elif chain, and the user
material's hand-written bash→wsl mapping. ``resolve_shell`` is now that one
place: the same name set, the same default (``powershell``) and the same
refusal for an unsupported name feed both lanes. What stays lane-local is only
who executes the launcher — the SYSTEM dispatcher script on the PC, or the
logged-in user's helper service (which stays the final allowlist authority,
#7105).
"""
from __future__ import annotations

from dataclasses import dataclass

SHELL_POWERSHELL = "powershell"
SHELL_CMD = "cmd"
SHELL_BASH = "bash"
#: #7105 — the helper's stage-1 names. The tool never accepts them; the
#: identity probe and the helper's own vocabulary use them.
SHELL_WHOAMI = "whoami"
SHELL_WSL = "wsl"

#: The tool vocabulary — what ``pc_shell*`` accepts as ``shell``.
PC_SHELL_NAMES = (SHELL_POWERSHELL, SHELL_CMD, SHELL_BASH)
#: Both lanes default to the same shell when a request omits the name.
PC_SHELL_DEFAULT_NAME = SHELL_POWERSHELL


class UnknownShellName(ValueError):
    """One shell name the shared table does not run, for either lane."""


@dataclass(frozen=True)
class SystemShellLaunch:
    """The nested-process launcher one SYSTEM dispatch runs on the PC.

    ``file`` is what the dispatcher's ``Get-Command`` must find; a miss is the
    same ``shell_unavailable`` exit 127 the inline branch used to report.
    ``prefix_args`` are the launcher's fixed arguments, ending in the flag that
    introduces the command itself (``-EncodedCommand`` for PowerShell, ``/c``
    is part of cmd's ``/d /s /c``, bash's ``-lc``). ``encode_command`` travels
    the command Base64(UTF-16LE) — the shape the nested PowerShell needs
    (#7068 pins the console encoding, the encoded command avoids every
    quoting rule).

    ``candidates`` (#7188 R4 ③) replaces the PATH hunt for shells whose bare
    name resolves to the wrong program. When it is non-empty the dispatcher
    ignores ``file`` entirely: it expands ``%...%`` in each candidate, probes
    them in order with ``Test-Path``, runs the first hit, and reports the same
    ``shell_unavailable`` exit 127 when none exists. bash carries the Git Bash
    roots — ``C:\\Windows\\System32\\bash.exe`` (WSL) is deliberately not a
    candidate: measured on COM1 (#7266 manual check), PATH resolution picked it
    and the run failed (exit 1, no output); on a customer PC the same name is
    WSL's bash. powershell and cmd keep ``candidates=()`` — their PATH
    resolution is the pinned behavior, unchanged; the candidate env line is
    only emitted for launches that carry candidates, so their three env lines
    and the tail's ``else`` branch stay the exact R4 ② bytes (argon #7287 (a);
    the residual risk — a parent process polluting
    ``PADIEM_MCP_SHELL_CANDIDATES`` — is a #7188 later item).
    """

    file: str
    prefix_args: tuple[str, ...]
    encode_command: bool
    candidates: tuple[str, ...] = ()


#: #7188 R4 ③ — bash means Git Bash, in both modes' terms: the SYSTEM lane
#: probes these Git for Windows standard install roots in order and fails with
#: ``shell_unavailable`` exit 127 when none exists. The values carry ``%...%``
#: so one static list covers system-wide (``ProgramFiles``, both architectures)
#: and per-user (``LocalAppData``) installs; the PC expands them at dispatch
#: time because the chat side cannot know the PC's filesystem.
#: ``%ProgramW6432%`` leads (argon #7287 (b) B-1): a 32-bit (WOW64) dispatcher
#: PowerShell redirects ``%ProgramFiles%`` to the x86 tree, so the 64-bit
#: standard install is only reachable through ``%ProgramW6432%``; on a 64-bit
#: PowerShell the first two candidates resolve to the same path and the
#: duplicate probe is a harmless ``Test-Path``.
GIT_BASH_CANDIDATES = (
    r"%ProgramW6432%\Git\bin\bash.exe",
    r"%ProgramFiles%\Git\bin\bash.exe",
    r"%ProgramFiles%\Git\usr\bin\bash.exe",
    r"%ProgramFiles(x86)%\Git\bin\bash.exe",
    r"%LocalAppData%\Programs\Git\bin\bash.exe",
)


_SYSTEM_LAUNCHES = {
    SHELL_POWERSHELL: SystemShellLaunch(
        file="powershell.exe",
        prefix_args=(
            "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-OutputFormat", "Text", "-EncodedCommand",
        ),
        encode_command=True,
    ),
    SHELL_CMD: SystemShellLaunch(
        file="cmd.exe", prefix_args=("/d", "/s", "/c"), encode_command=False,
    ),
    SHELL_BASH: SystemShellLaunch(
        file="bash.exe", prefix_args=("-lc",), encode_command=False,
        candidates=GIT_BASH_CANDIDATES,
    ),
}


def resolve_shell(name: str, *, lane: str):
    """Resolve one tool shell name for one lane.

    ``lane="system"`` returns the :class:`SystemShellLaunch` the dispatcher
    runs. ``lane="user"`` returns the helper shell name the request material
    carries — ``bash`` runs inside the user's WSL, which is #7105's vocabulary
    meeting, and the Windows shells pass through as the shell the user session
    runs. An unsupported name raises :class:`UnknownShellName` for both lanes
    alike, so neither lane grows a private name list or a private default.
    """
    if not isinstance(name, str) or name not in PC_SHELL_NAMES:
        raise UnknownShellName(f"shell is not one this lane runs: {name!r}")
    if lane == "system":
        return _SYSTEM_LAUNCHES[name]
    if lane == "user":
        return SHELL_WSL if name == SHELL_BASH else name
    raise ValueError(f"unknown lane: {lane!r}")


def resolve_user_helper_shell(name: str, *, command: str) -> str:
    """The helper shell one user-mode request runs.

    The identity probe is the one command that means the same thing in every
    shell, so it maps to the helper's dedicated ``whoami`` shell (#7105). That
    mapping is about the command, not a shell preference, and it keeps the
    measured output the tool contract promises.
    """
    if isinstance(command, str) and command.strip() == "whoami":
        return SHELL_WHOAMI
    return resolve_shell(name, lane="user")


def system_launch_env_lines(launch: SystemShellLaunch) -> str:
    """The env lines that carry a resolved launcher into the dispatcher script.

    The script is static PowerShell text with no shell branch left (#7188 R4
    ②); these assignments are the only shell-specific bytes in one dispatch,
    and they come from this table, not from a call site. The values are table
    constants, so the single-quote wrapping is exact. The candidate line
    (#7188 R4 ③) is emitted only for launches that carry candidates —
    powershell and cmd keep the exact three lines they always had.
    """
    lines = (
        "$env:PADIEM_MCP_SHELL_FILE='" + launch.file + "';"
        "$env:PADIEM_MCP_SHELL_ARGS='" + " ".join(launch.prefix_args) + "';"
        "$env:PADIEM_MCP_SHELL_ENC='" + ("1" if launch.encode_command else "0") + "';"
    )
    if launch.candidates:
        lines += ("$env:PADIEM_MCP_SHELL_CANDIDATES='"
                  + ";".join(launch.candidates) + "';")
    return lines
