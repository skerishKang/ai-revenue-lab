"""#4139 trial — MeshCentral terminal command port for the Oracle executor.

One command runs through the OFFICIAL ``meshctrl.js`` client
(``runcommand --reply``) over the same private path the TXT read already uses:
Claw Worker → Workers VPC Service → COM1 QUIC tunnel → local ssh -L → the
Oracle MeshCentral on 127.0.0.1:4443.

Two facts drive this module:

* ``runcommand --reply`` returns the *device shell transcript*, and the shell is
  chosen by MeshCentral, not by this module. The command is therefore sent to
  the device PowerShell with an explicit ``$LASTEXITCODE`` sentinel appended, so
  the exit code is the one the PC actually reported. It is never inferred from
  "the request was accepted" and never defaulted to 0.
* A console that never answers produces NO transcript at all. That is a real
  outcome (``no_reply`` / ``timed_out``) with an unobserved exit code, never a
  silent success. A console that answers with the sentinel but no number is
  ``no_exit_code``: the output is complete and the code stays unobserved.

The bytes returned here are the PC output verbatim, including CR/LF and any
leading/trailing whitespace, minus the envelope line and the sentinel line this
module itself added.

One more fact governs the shape of this module: the agent runs one command child at
a time and answers a later ``runcommand`` with "already busy" while that child
lives, so a command that never finished leaves every later operation on that PC
without a reply. ``meshctrl shell`` reaches the same agent over a terminal tunnel,
which is the channel that kept working while the console was held; the owner's stop
(#6059) and the console sweep below both travel it. The wait for an answer carries a
deadline and the work on the PC never does, and the sweep is what tells the two
apart on the PC itself rather than by guesswork here.

The envelope exists because of what the PC's own console does with Korean. A
Windows console answers in its code page (cp949 on 한국어 installations), the
MeshCentral agent puts that reply on a WebSocket *text* frame, and MeshCentral
rejects the frame with ``WS_ERR_INVALID_UTF8`` — the command ran, and the answer
was destroyed before anyone could read it. The reply is therefore Base64 of its
UTF-8 bytes, so only ASCII ever crosses the frame on the way back. The command
itself travels as MeshCentral's own UTF-8 JSON, which the server encodes.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

from .contracts import ContractError
from .local_agent_meshcentral_private_reader import (
    _MESHCTRL_STDIN_BOOTSTRAP,
    _MESHCTRL_STDIN_LINE_BOOTSTRAP,
)

#: Marker appended to the requested command so the PC reports its own exit code.
EXIT_SENTINEL = "__PADIEM_EXIT__"
#: #5573: the PC's own console label for the encoded reply body.
ENVELOPE_PREFIX = "PADIEM_B64="
#: #4139: a command is ordinary text. Korean, quotes, tabs and several lines are
#: allowed, and there is no product length rule — the former 512- and
#: 8,192-character caps were trial limits. Only NUL and CR are refused, because
#: both break the transport they travel on: NUL cannot exist in an OS argv
#: string, and CR ends the transcript line the exit sentinel is parsed from.
_COMMAND_BODY = re.compile(r"[^\x00\r]+")
#: Linux fixes one argv element at MAX_ARG_STRLEN = PAGE_SIZE * 32 = 131,072
#: bytes (``include/uapi/linux/binfmts.h``, the limit ``execve(2)`` documents);
#: the kernel counts the string together with its terminating NUL. The wrapped
#: command is exactly one ``--run`` argument on the Oracle host, so a command
#: that cannot be exec'd is refused here with its cause instead of dying as an
#: opaque E2BIG. The aggregate argv-plus-environment ceiling depends on that
#: host's stack rlimit and is not guessed at here; it sits far above anything a
#: dispatch row can carry.
_MAX_ARGV_ELEMENT_BYTES = 131_072
_SENTINEL_LINE = re.compile(rb"__PADIEM_EXIT__(-?\d+)?")
_ENVELOPE_WHITESPACE = re.compile(rb"\s+")
METHOD_LABEL = "powershell_runcommand_reply"
#: stdout and stderr travel merged (``2>&1`` inside the captured expression);
#: the conversation says so.
MERGED_STREAMS = True
#: Owner decision 2026-10-28 (#5895): the command output carries no PADIEM byte
#: ceiling. A large transcript is returned whole; the wire and memory ceilings
#: of the platforms that carry it remain the only bounds.
MAX_COMMAND_BYTES: int | None = None
MAX_TRANSCRIPT_BYTES: int | None = None


class MeshCentralCommandRefused(ValueError):
    """Bounded refusal of one command run. Never carries output or secrets."""


@dataclass(frozen=True, slots=True)
class MeshCentralCommandOutcome:
    """What one real command run produced, exactly as observed."""

    #: "exited" | "timed_out" | "no_reply" | "no_exit_code" | "output_too_large"
    #: | "bad_reply"
    #: no_reply means the console never answered; no_exit_code means it answered
    #: completely and PowerShell had no code to report; bad_reply means it
    #: answered but the envelope could not be read, so nothing is claimed about
    #: what the PC printed.
    termination: str
    exit_code: int | None
    output: bytes
    method: str = METHOD_LABEL
    merged_streams: bool = MERGED_STREAMS
    #: How many times this command found the PC's console held by a process that
    #: no dispatch owns. Communication state, not a judgement about the work.
    line_blocked: int = 0
    #: How many times such a process was actually ended. A detection without a
    #: clearing is reported as it happened, never as a recovery.
    line_cleared: int = 0


@dataclass(frozen=True, slots=True)
class MeshCentralLineSweep:
    """What one out-of-band console sweep observed on the PC.

    ``observed`` is the honest split the owner rule requires: a session that could
    not bring its answer back is ``observed=False`` and is reported as unobserved,
    never as a clean console. The ending decision itself is taken on the PC, so a
    lost answer cannot make this sweep kill more than an answer.
    """

    #: Which scope this sweep was allowed to reach: see ``SWEEP_MODE_ABANDONED``.
    mode: str
    #: The terminal session reached the PC and its bound expired or answered.
    ran: bool
    #: A verdict frame came back and was read.
    observed: bool
    #: The PC answered "a dispatch this connector owns is running right now".
    running: bool
    #: A server-side claim on this PC stopped the sweep before it ran. Nothing was
    #: looked at and nothing was ended, and that is reported as itself rather than
    #: as a console that was asked and found clean.
    gated: bool = False
    #: Agent children that were holding the console when the sweep ran.
    found: tuple[dict[str, Any], ...] = ()
    #: Process ids whose tree the PC ended.
    killed: tuple[int, ...] = ()
    #: Bounded reason for a sweep that produced nothing; never an output blob.
    error: str = ""


def _bounded_command(value: Any) -> str:
    if not isinstance(value, str):
        raise MeshCentralCommandRefused("command must be text")
    if not value:
        raise MeshCentralCommandRefused("command must not be empty")
    if _COMMAND_BODY.fullmatch(value) is None:
        raise MeshCentralCommandRefused(
            "command must not contain NUL or carriage return"
        )
    # Trailing whitespace is dropped so the appended sentinel statement can
    # never be swallowed by an unterminated line; interior lines are untouched.
    return value.rstrip(" \t\r\n")


#: #5895: how a stopped command is ended ON THE PC. Every command this lane runs
#: leaves one file behind, named by its own dispatch id and holding its process id,
#: and removes it on the way out. The stop reads that file and kills that process
#: tree - nothing else. A name rather than a search, because the agent's console
#: task queue is serial: a stop that had to look for the process would be queued
#: behind the very command it is trying to end, which is the failure measured on
#: 2026-10-28 (a cancelled sweep held every later PC operation for minutes until a
#: person killed it by hand).
PC_CANCEL_PID_FILE_PREFIX = "padiem-dispatch-"
#: A dispatch id is this module's own identifier, and it is interpolated into a
#: PowerShell literal on the customer's PC, so it is refused unless it is exactly
#: what the server issues. No customer text reaches this position.
_DISPATCH_ID = re.compile(r"^dsp_[0-9a-f]{16,64}$")
#: The stop itself is a short console session, bounded so a wedged agent tunnel can
#: never become the new way to hold a PC.
CANCEL_KILL_WAIT_SECONDS = 15


def _checked_dispatch_id(value: Any) -> str:
    if not isinstance(value, str) or _DISPATCH_ID.fullmatch(value) is None:
        raise MeshCentralCommandRefused("dispatch_id is not a dispatch identifier")
    return value


#: A host tag is this connector's own name, written into a file on the customer's
#: PC and read back into a comparison. Anything that is not a hostname character is
#: dropped rather than escaped, so a tag can never carry a quote into a literal.
_HOST_TAG = re.compile(r"[^0-9A-Za-z._-]")


def _checked_host_tag(value: Any) -> str:
    if not isinstance(value, str):
        raise MeshCentralCommandRefused("the executor host tag must be text")
    return _HOST_TAG.sub("", value)[:64]


def _local_host_tag() -> str:
    """This executor's own name, the only thing that may claim a marker as ours."""
    import socket

    return _checked_host_tag(socket.gethostname())


def _pid_file_literal(dispatch_id: str) -> str:
    """The PowerShell expression for this dispatch's own marker file on the PC.

    ``GetTempPath`` is the folder the agent's own account writes its scratch to, so
    the command that starts and the stop that ends it resolve the same path without
    either one being told where the PC keeps its temporary files.
    """
    return ("[IO.Path]::GetTempPath()+'" + PC_CANCEL_PID_FILE_PREFIX
            + _checked_dispatch_id(dispatch_id) + ".pid'")


def cancel_kill_command(dispatch_id: str) -> str:
    """The one-liner that ends exactly one stopped dispatch, and its marker.

    Scoped by construction: it reads that dispatch's own pid file, kills that
    process tree, and deletes the file. It never names an image, a service or a
    window title, so the agent and any other customer work on the PC cannot be
    reached through it. When the file is absent the command does nothing, which is
    the normal case - a command that finished on its own has already removed it.
    """
    marker = "$__padiem_stop"
    return (
        "$ErrorActionPreference='SilentlyContinue';"
        f"{marker}={_pid_file_literal(dispatch_id)};"
        f"if (Test-Path -LiteralPath {marker}) {{"
        f"$__padiem_kill=(Get-Content -LiteralPath {marker} | Select-Object -First 1);"
        "if ($__padiem_kill) { & taskkill /T /F /PID $__padiem_kill | Out-Null };"
        f"Remove-Item -LiteralPath {marker} -Force }}"
    )


#: Owner decision 2026-10-29, connector stability standard 2 and 3: the wait for an
#: ANSWER on the PC's console carries a deadline, the work on the PC does not. This
#: is the communication bound only - a command the PC is actually running is never
#: interrupted by it, because the sweep asks the PC whether that command is alive
#: before it touches anything.
LINE_STALL_WAIT_SECONDS = 120
#: #82 root fix (CTO standard 2), DEFAULT OFF. The agent serves one `runcommand` child
#: and answers a later request "already busy" and drops it, so one long command holds
#: every later one on that machine. The terminal tunnels are a different lane: the
#: source shows N per node, no cap, alive until `endtunnel`. With this flag on, each
#: dispatch runs on its own session. Off, nothing about the existing path changes -
#: the flag is turned on by the operator only after the queue cutover and its
#: observation window, never by this module.
SESSION_COMMAND_LANE_ENV = "PADIEM_MESH_SESSION_COMMAND_LANE"
#: The console probe and its clearing (#6106, #6113), DEFAULT OFF as of 2026-10-29.
#: Qoder's live probe showed that `meshctrl shell` input is echoed back and never
#: executed on COM1's old agent, COM2's and a brand-new CGI-1 install alike (a 71-byte
#: reply that merely mirrors what was typed, no token, no prompt, no error). The probe
#: therefore cannot work through that channel today, and it ran on every command that
#: carried a dispatch id. Until the transport is fixed or replaced, the safe default
#: is the queue lane exactly as it was before the probe existed: the operator turns
#: this on only if they know their agent's shell lane executes input.
LINE_PROBE_ENV = "PADIEM_MESH_LINE_PROBE"
#: Communication bounds for the session lane. Opening a session is not work: the
#: password and the script must reach the shell and something must come back. Past
#: this the session is treated as not opened and the caller falls back.
SESSION_OPEN_TIMEOUT_SECONDS = 20
SESSION_CANCEL_KILL_WAIT_SECONDS = 15
#: The sweep rides the same terminal session the stop rides, so it inherits the
#: stop's bound: a sweep that cannot reach the PC must never become the new way to
#: hold that PC.
LINE_SWEEP_WAIT_SECONDS = CANCEL_KILL_WAIT_SECONDS
#: How many in-progress dispatches may be named as protected on one sweep. The
#: executor's own active set is one in the normal case; the bound keeps a
#: malformed caller from stretching a script line on a customer machine.
LINE_SWEEP_KEEP_LIMIT = 8
#: The marker file's own prefix length, used to read a dispatch id back out of the
#: file name the command left behind.
_MARKER_PREFIX_LENGTH = len(PC_CANCEL_PID_FILE_PREFIX)
#: Answer frame for the sweep. The script builds it from two literals so the
#: terminal's echo of the script itself can never read back as an answer.
SWEEP_SENTINEL = "__PADIEM_SWEEP__"
_BASE64_BODY = re.compile(rb"[A-Za-z0-9+/=]+")
#: What one terminal session may accumulate on this host. The answer line is a
#: few hundred bytes; the limit only bounds a chatty terminal, and a session that
#: runs past it reports its verdict as unobserved instead of growing without end.
HANDOFF_CAPTURE_LIMIT = 262_144


def _keep_id_literals(dispatch_id: str | None, keep_dispatch_ids) -> list[str]:
    """The dispatch ids whose work on the PC this sweep must never touch.

    Every id passes the same grammar the stop applies, so nothing that is not a
    dispatch identifier this module understands can reach a PowerShell literal.
    """
    ids: list[str] = []
    for value in ((dispatch_id,) if dispatch_id is not None else ()) + tuple(
        keep_dispatch_ids or ()
    ):
        checked = _checked_dispatch_id(value)
        if checked not in ids:
            ids.append(checked)
        if len(ids) >= LINE_SWEEP_KEEP_LIMIT:
            break
    return ids


#: Two scopes, because the two moments that ask for them know different things.
#: ``abandoned`` is the pre-flight scope: it ends only a process a PADIEM dispatch
#: left its own marker on, so a person's terminal on the same PC is never touched
#: while the line is provably idle. ``held`` is the scope after the wait cap: the
#: command this connector sent produced nothing and the PC says it never started,
#: which means whatever holds the console is holding it for no dispatch - measured
#: on 2026-10-29 as a diagnostic PowerShell that survived eleven hours.
SWEEP_MODE_ABANDONED = "abandoned"
SWEEP_MODE_HELD = "held"
SWEEP_MODES = (SWEEP_MODE_ABANDONED, SWEEP_MODE_HELD)


def _sweep_head(dispatch_id: str | None, keep: list[str]) -> str:
    """The part both sweep scopes share: name the agent, the markers, the protected set.

    Everything is read from OS process records and from the marker file each command
    leaves for itself. No image name, service name, window title or output text is
    matched anywhere, so a verdict cannot be talked into firing by a string that
    happens to appear on the screen.
    """
    own = (
        "$__padiem_own=" + _pid_file_literal(dispatch_id) + ";"
        "if (Test-Path -LiteralPath $__padiem_own) {"
        " $__padiem_ours=[uint32]((Get-Content -LiteralPath $__padiem_own"
        " | Select-Object -First 1))};"
    ) if dispatch_id is not None else ""
    return (
        "$ErrorActionPreference='SilentlyContinue';"
        "$__padiem_self=$PID;"
        "$__padiem_agent=(Get-CimInstance Win32_Process -Filter "
        '"ProcessId=$__padiem_self").ParentProcessId;'
        "$__padiem_temp=[IO.Path]::GetTempPath();"
        "$__padiem_ours=$null;" + own +
        "$__padiem_live=$null;"
        "if ($__padiem_ours) { $__padiem_live=Get-CimInstance Win32_Process "
        '-Filter "ProcessId=$__padiem_ours" };'
        "$__padiem_keep=@(" + ",".join("'" + i + "'" for i in keep) + ");"
        "$__padiem_safe=@($__padiem_self);$__padiem_orphan=@();"
        # The agent is named by walking up from this session's own process, so the
        # family chain is protected whatever the agent put between itself and this
        # shell. A sweep that ended its own session would answer nothing, which is
        # the failure mode this whole lane exists to avoid.
        "$__padiem_walk=$__padiem_self;$__padiem_hop=0;"
        "while ($__padiem_walk -and $__padiem_hop -lt 8) {"
        " $__padiem_pp=(Get-CimInstance Win32_Process -Filter "
        '"ProcessId=$__padiem_walk").ParentProcessId;'
        " if (-not $__padiem_pp) { break };"
        " $__padiem_safe += $__padiem_pp;"
        " $__padiem_walk=$__padiem_pp;$__padiem_hop++};"
        # Every command names itself in the agent's own temporary folder. Read the
        # folder: a marker this connector still owns protects that tree, and a
        # marker nobody owns is the orphan this sweep exists to find. The counter is
        # cleared per file, because a read that failed must not carry the previous
        # file's process id onto the next one.
        "foreach ($__padiem_f in Get-ChildItem -LiteralPath $__padiem_temp "
        "-Filter '" + PC_CANCEL_PID_FILE_PREFIX + "*.pid') {"
        " $__padiem_id=$__padiem_f.BaseName.Substring(" + str(_MARKER_PREFIX_LENGTH)
        + ");$__padiem_p=$null;$__padiem_h='';"
        "$__padiem_v=@((Get-Content -LiteralPath $__padiem_f.FullName "
        "| Select-Object -First 2));"
        "$__padiem_p=[uint32]$__padiem_v[0];$__padiem_h=[string]$__padiem_v[1];"
        " if ($__padiem_keep -contains $__padiem_id) {"
        " if ($__padiem_p) { $__padiem_safe += $__padiem_p } }"
        " elseif ($__padiem_p) { $__padiem_orphan +="
        " @{id=$__padiem_id;pid=$__padiem_p;host=$__padiem_h;"
        "file=$__padiem_f.FullName} }};"
        "$__padiem_found=@();$__padiem_killed=@();"
    )


def _sweep_frame(mode: str) -> str:
    return (
        "$__padiem_out=@{mode='" + mode + "';agent=$__padiem_agent;"
        " running=[bool]($__padiem_live -ne $null);"
        " found=$__padiem_found; killed=$__padiem_killed;"
        " self=[uint32]$__padiem_self} | ConvertTo-Json -Compress -Depth 5;"
        ' Write-Output ("__PADIEM_" + "SWEEP__"'
        " + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes([string]$__padiem_out)))"
    )


def sweep_script(
    *,
    dispatch_id: str | None = None,
    keep_dispatch_ids=(),
    mode: str = SWEEP_MODE_ABANDONED,
    host_tag: str | None = None,
) -> str:
    """Free the PC's serial console from a process that no dispatch owns.

    The agent runs one command child at a time and drops a later request as
    "already busy" while it lives, so a PowerShell left behind by an abandoned
    command leaves every later operation on that PC without a reply - measured twice
    on 2026-10-28 and 2026-10-29, and ended by hand both times. The script decides on
    the PC, so the safety never depends on an answer that may not come back:

    * the agent itself is never a candidate. It is read as the parent, and the
      parent chain of this very session is how that parent is named - no image
      name is written here;
    * when the marker of a dispatch this connector owns points at a live process,
      the PC is running real work and NOTHING is ended. That single condition is
      the whole difference between a ceiling on the work and a ceiling on the
      wait for an answer;
    * a process whose own dispatch is named in the protected set is skipped, so a
      command another lane runs on the same PC keeps running;
    * this session's own process is skipped, because ending it would end the
      answer the script is about to print;
    * in the pre-flight scope, a marker left by the other executor host is skipped
      too. Two hosts can hold a claim on one PC during a failover handover, and a
      command that is running on the partner's authority is not this one's to
      clear;
    * an orphan marker is removed with its tree, so the next sweep can never aim a
      stale process id at a process that was started later under that number.

    The verdict comes back as one Base64 line. Only ASCII may cross that frame:
    a Korean process name in a UTF-8 reply frame is what MeshCentral drops, and a
    dropped frame is a PC that looks healthy while its answer is gone.
    """
    if mode not in SWEEP_MODES:
        raise MeshCentralCommandRefused("the sweep scope is not one this module knows")
    keep = _keep_id_literals(dispatch_id, keep_dispatch_ids)
    head = _sweep_head(dispatch_id, keep)
    if mode == SWEEP_MODE_ABANDONED:
        # Nothing here is proven blocked, so the reach is only ever this host's own
        # abandoned work.
        if host_tag:
            mine = (
                " if ($__padiem_o.host -ne '"
                + _checked_host_tag(host_tag) + "') { continue };"
            )
        else:
            # Without a tag there is no way to tell our own leftover from the
            # failover partner's running command, so this scope ends nothing at all.
            # The held scope, taken only once a line is provably dead, is the
            # recovery path for a port that does not name itself.
            mine = " continue;"
        body = (
            "if (-not $__padiem_live) {"
            " foreach ($__padiem_o in $__padiem_orphan) {"
            + mine +
            ' $__padiem_c=Get-CimInstance Win32_Process -Filter '
            '"ProcessId=$($__padiem_o.pid)";'
            " if ($__padiem_safe -contains $__padiem_o.pid) { continue };"
            " if ($__padiem_c) {"
            " $__padiem_found += @{pid=$__padiem_o.pid; name=[string]$__padiem_c.Name;"
            " created=[string]$__padiem_c.CreationDate; dispatch=$__padiem_o.id};"
            " & taskkill /T /F /PID $__padiem_o.pid | Out-Null;"
            " $__padiem_killed += $__padiem_o.pid };"
            " Remove-Item -LiteralPath $__padiem_o.file -Force }};"
        )
    else:
        # The held-line scope: nothing this connector owns is running, so every
        # console process the agent spawned is holding that console for work no
        # dispatch claims. Their markers go with them, for the same stale-pid reason.
        body = (
            "if (-not $__padiem_live) {"
            " foreach ($__padiem_k in Get-CimInstance Win32_Process -Filter"
            ' "ParentProcessId=$__padiem_agent") {'
            " if ($__padiem_safe -contains $__padiem_k.ProcessId) { continue };"
            " $__padiem_found += @{pid=[uint32]$__padiem_k.ProcessId;"
            " name=[string]$__padiem_k.Name; created=[string]$__padiem_k.CreationDate};"
            " & taskkill /T /F /PID $__padiem_k.ProcessId | Out-Null;"
            " $__padiem_killed += [uint32]$__padiem_k.ProcessId }};"
            " foreach ($__padiem_o in $__padiem_orphan) {"
            " Remove-Item -LiteralPath $__padiem_o.file -Force };"
        )
    return head + body + _sweep_frame(mode)


def _session_lane_enabled(explicit: bool | None, environ=None) -> bool:
    """Whether a command runs on its own terminal session (#82, default off).

    Off is the shipped behaviour: the runcommand queue plus the line healing (#6106,
    #6113). The operator turns it on in the executor's unit after the queue cutover
    and its observation window, and nothing here changes the default.
    """
    if explicit is not None:
        return explicit is True
    source = os.environ if environ is None else environ
    return (source.get(SESSION_COMMAND_LANE_ENV) or "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _line_probe_enabled(explicit: bool | None, environ=None) -> bool:
    """Whether the console probe runs for a command (#6106/#6113), default NO.

    Off is the shipped behaviour since 2026-10-29: the shell channel was measured
    echoing input without executing it, so a probe there reports nothing and a
    clearing there kills nothing. Enabled only by an explicit value, never by absence.
    """
    if explicit is not None:
        return explicit is True
    source = os.environ if environ is None else environ
    return (source.get(LINE_PROBE_ENV) or "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _session_payload(raw: bytes) -> bytes:
    """The reply from the last envelope marker onward, with terminal noise dropped.

    A terminal writes prompts, echoes and escape sequences around what the PC
    actually printed. The envelope marker is the boundary: everything before its last
    occurrence is the session talking, not the command.
    """
    marker = ENVELOPE_PREFIX.encode("ascii")
    position = raw.rfind(marker)
    if position < 0:
        # No envelope means nothing this lane printed as an answer. A terminal that
        # only mirrors its input must not be shown as the command's output: the reply
        # is noise, and the caller reports an unanswered console.
        return b""
    tail = raw[position:]
    # The shell prompt returns right after the sentinel line, and a prompt is not part
    # of the reply: keep the frame and drop whatever the terminal appended after it.
    index = tail.find(EXIT_SENTINEL.encode("ascii"))
    if index < 0:
        return tail
    end = tail.find(b"\n", index)
    return tail if end < 0 else tail[:end + 1]


def _may_clear(line_guard: Callable[[], bool] | None,
               phase: Callable[[str], None]) -> bool:
    """Whether a held console may be cleared, as the caller's authority answers.

    No guard at all is a clear "no": a port composed without the server's view of
    the PC cannot tell its own idle from its failover partner's running command, and
    guessing is the one thing that would end real work. A guard that raises, times
    out or answers anything other than ``True`` is the same "no".
    """
    if line_guard is None:
        phase("line_gate_closed")
        return False
    try:
        allowed = line_guard() is True
    except Exception:
        allowed = False
    if not allowed:
        phase("line_gate_busy")
    return allowed


def parse_sweep_reply(raw: bytes) -> dict[str, Any] | None:
    """Read one sweep verdict frame out of a terminal session, or say it is unreadable.

    A terminal echoes what was typed and interleaves prompts with the answer, so
    the frame is taken from its LAST occurrence and only for as far as Base64 runs.
    ``None`` means no verdict came back. It is never read as "nothing was left
    behind": the caller reports the sweep as unobserved instead of clean.
    """
    if not isinstance(raw, (bytes, bytearray)):
        return None
    data = bytes(raw)
    marker = SWEEP_SENTINEL.encode("ascii")
    position = data.rfind(marker)
    if position < 0:
        return None
    body = _BASE64_BODY.match(data, position + len(marker))
    if body is None:
        return None
    try:
        decoded = base64.b64decode(body.group(0), validate=True).decode("utf-8")
        verdict = json.loads(decoded)
    except Exception:
        return None
    return verdict if isinstance(verdict, dict) else None


def _wrap(command: str, dispatch_id: str | None = None, host_tag: str | None = None,
          split_markers: bool = False) -> str:
    """Run one command on the PC and bring its output back as ASCII Base64.

    Three rules carry it:

    * ``[Console]::OutputEncoding`` is set to UTF-8 first, so the console writes
      the script's own bytes instead of the machine's code page;
    * the merged stdout+stderr string is Base64-encoded **on the PC**, so the
      reply frame carries only Base64 characters whatever the console produced —
      this is what stops a cp949 answer from being destroyed in transit;
    * the captured run is inside ``try``/``catch``, because a command carrying
      ``-ErrorAction Stop`` raises a *terminating* error, and an uncaught one
      would skip the envelope and the exit sentinel entirely. The error record's
      own text then travels inside the envelope instead of being lost.

    Only the reply is encoded. The command itself travels as MeshCentral's own
    UTF-8 JSON — measured on the real PC, a Korean path in the command reaches
    the agent intact — and encoding it too would shrink the argument the OS can
    exec by a third for no transport gain. The merge is applied to the whole
    statement (``2>&1`` inside the captured expression), which is what #4139
    measured: without it, a command that writes to stderr either loses that text
    or never returns a transcript at all. ``$LASTEXITCODE`` is PowerShell's
    record of the last native command, so the sentinel reports the real remote
    exit code, and a cmdlet-only pipeline still leaves it empty rather than 0.

    With a dispatch id the wrapped script also leaves, and removes, that
    dispatch's marker file - see ``cancel_kill_command``. The marker is two lines:
    the process id first, because that is all the stop has ever read and all it
    will read, and this executor host's own tag second. The tag is what lets a
    console sweep tell its own leftover from the leftover of the failover partner
    that claimed the same PC during a handover - a distinction that has to exist
    before anything on a customer machine may be ended. Without a dispatch id it is
    the same bytes as before, so nothing about a command's own result can change.
    """
    marks = ""
    clears = ""
    if dispatch_id is not None:
        marker = _pid_file_literal(dispatch_id)
        marks = (
            " $__padiem_pidfile=" + marker
            + "; Set-Content -LiteralPath $__padiem_pidfile -Value $PID -Encoding ascii;"
        )
        if host_tag:
            marks += (
                " Add-Content -LiteralPath $__padiem_pidfile -Value '"
                + _checked_host_tag(host_tag) + "' -Encoding ascii;"
            )
        clears = (
            " if ($__padiem_pidfile) {"
            " Remove-Item -LiteralPath $__padiem_pidfile -Force -ErrorAction SilentlyContinue };"
        )
    return (
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
        " $__padiem=$null;" + marks +
        " try { $__padiem=(& { " + command + " } 2>&1 | Out-String)"
        " } catch { $__padiem=($_ | Out-String) };" + clears +
        # A terminal session echoes the script the shell was handed. The markers are
        # assembled from two literals on that lane, so the echo can never contain the
        # joined token while the bytes the PC prints stay exactly the same.
        (
            ' Write-Output ("PADIEM_" + "B64=" + '
            "[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes([string]$__padiem)));"
            ' Write-Output ("__PADIEM_" + "EXIT__" + $LASTEXITCODE)'
            if split_markers else
            ' Write-Output ("' + ENVELOPE_PREFIX + '" + '
            "[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes([string]$__padiem)));"
            ' Write-Output ("' + EXIT_SENTINEL + '" + $LASTEXITCODE)'
        )
    )


def _unwrap_envelope(output: bytes) -> tuple[bytes, bytes] | None:
    """Split one transcript into (text before the envelope, decoded body).

    ``None`` means the reply is not a readable envelope: no marker, a payload
    that is not Base64, or bytes that are not valid UTF-8. A caller that got a
    console answer must not present mangled bytes as if the PC had printed them.
    """
    marker = ENVELOPE_PREFIX.encode("ascii")
    position = output.find(marker)
    if position < 0:
        return None
    prefix = output[:position]
    # Whitespace is not part of Base64 and a long body may be wrapped by the
    # console, so the token is read as the payload it is, not as one line.
    payload = _ENVELOPE_WHITESPACE.sub(b"", output[position + len(marker):])
    try:
        body = base64.b64decode(payload, validate=True)
    except Exception:
        return None
    try:
        body.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return prefix, body


def _read_some(process: Any, timeout_seconds: float) -> bytes:
    """One bounded read from a child's stdout, empty when nothing is ready."""

    import selectors
    import time

    stdout = getattr(process, "stdout", None)
    if stdout is None:
        return b""
    try:
        stdout.fileno()
    except Exception:
        # Not an OS pipe (a test double, or an already-buffered stream): a
        # plain read is the only option and returns whatever is available.
        return stdout.read(65536) or b""
    deadline = time.monotonic() + timeout_seconds
    selector = selectors.DefaultSelector()
    try:
        selector.register(stdout, selectors.EVENT_READ)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return b""
            events = selector.select(remaining)
            if not events:
                return b""
            chunk = stdout.read(65536)
            return chunk or b""
    finally:
        selector.close()


def parse_transcript(raw: bytes) -> tuple[str, int | None, bytes]:
    """Split one ``--reply`` transcript into (termination, exit code, output).

    ``meshctrl`` prints the agent's console result with ``console.log``, which
    appends exactly one newline of its own; that single byte is removed so the
    returned output is the PC's bytes only. Everything else is preserved
    verbatim, including CR/LF and edge whitespace.
    """
    if not isinstance(raw, (bytes, bytearray)):
        return "no_reply", None, b""
    data = bytes(raw)
    if data.endswith(b"\n"):
        data = data[:-1]
    index = data.rfind(EXIT_SENTINEL.encode("ascii"))
    if index < 0:
        return "no_reply", None, data
    start = data.rfind(b"\n", 0, index) + 1
    end = data.find(b"\n", index)
    if end < 0:
        end = len(data)
    line = data[start:end].strip()
    match = _SENTINEL_LINE.fullmatch(line)
    if match is None:
        return "no_reply", None, data
    raw_code = match.group(1)
    # Drop the sentinel line (and the newline that ended it) from the output.
    output = data[:start] + (data[end + 1:] if end < len(data) else b"")
    code = None if raw_code is None else int(raw_code)
    envelope = _unwrap_envelope(output)
    if envelope is None:
        # The console answered, but not with a readable envelope. This is not a
        # silent console and not a truncation: it is a reply that cannot be
        # presented as the PC's output, so it keeps its own outcome.
        return "bad_reply", code, b""
    prefix, body = envelope
    if prefix:
        body = prefix + body
    if raw_code is None:
        # The sentinel printed an empty value. That is not a console that never
        # answered: PowerShell records `$LASTEXITCODE` only for "the exit code of
        # the last native program or PowerShell script that ran" (Microsoft,
        # about_Automatic_Variables), so a pipeline made only of cmdlets and .NET
        # calls leaves it empty while still returning its whole output. The code
        # stays unobserved here and is never turned into 0.
        return "no_exit_code", None, body
    return "exited", int(raw_code), body


class _TerminalHandoff:
    """The pty ``meshctrl shell`` insists on, with its input already queued.

    The client reads the credential from standard input and then pipes that same
    stream into the PC's terminal, so the password is one line and the command is
    the bytes after it, and closing the handle ends the session. ``setRawMode`` is
    not a function on a pipe, which is why a terminal device is needed at all.
    """

    def __init__(self, write_bytes: bytes) -> None:
        import pty

        self._master, self.slave = pty.openpty()
        self.received = bytearray()
        os.write(self._master, write_bytes)

    def _pump(
        self,
        seconds: float,
        done: Callable[[bytes], bool] | None = None,
    ) -> None:
        import select

        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if select.select([self._master], [], [], 0.2)[0]:
                try:
                    chunk = os.read(self._master, 65536)
                except OSError:
                    break
                if chunk == b"":
                    break
                if len(self.received) < HANDOFF_CAPTURE_LIMIT:
                    self.received.extend(chunk)
                if done is not None and done(bytes(self.received)):
                    break
        self.close()

    def wait_closed(self, seconds: float) -> None:
        self._pump(seconds)

    def read(self, timeout: float) -> bytes:
        """One bounded read from the terminal; empty when nothing arrived."""
        import select

        try:
            if not select.select([self._master], [], [], timeout)[0]:
                return b""
            return os.read(self._master, 65536)
        except OSError:
            return b""

    def wait_for(self, done: Callable[[bytes], bool], seconds: float) -> bytes:
        """Read the session until the answer is complete, or until the bound ends."""
        self._pump(seconds, done)
        return bytes(self.received)

    def close(self) -> None:
        for handle in (self._master, self.slave):
            try:
                os.close(handle)
            except OSError:
                pass


class MeshCentralCliCommandPort:
    """The concrete command run over the official ``meshctrl.js`` client.

    ``command_runner`` is injected, so the process boundary is explicit and
    testable: it receives argv and a one-use ``input`` string and must return an
    object exposing ``returncode`` (a ``subprocess.run`` result fits). The
    operator password travels over the child's stdin exactly like the read port.
    """

    def __init__(
        self,
        *,
        command_runner: Callable[..., Any],
        meshctrl_js: str,
        login_user: str,
        password_provider: Callable[[], str],
        url: str = "wss://127.0.0.1:4443",
        work_dir: str | None = None,
        popen_factory: Callable[..., Any] | None = None,
        pty_factory: Callable[[], Any] | None = None,
        host_tag: str | None = None,
    ) -> None:
        if not callable(command_runner):
            raise ContractError("meshcentral command requires an injected command runner")
        # #4139: the child is read in chunks, so memory tracks what the PC
        # actually sent. #5895 removed the byte ceiling: the transcript is
        # returned whole, and the chunked read stays as the streaming shape.
        self._popen_factory = popen_factory
        # The stop needs a terminal device for the official client's shell; a test
        # injects a stand-in, and production uses the pty above.
        self._pty_factory = pty_factory if callable(pty_factory) else _TerminalHandoff
        if not isinstance(meshctrl_js, str) or not meshctrl_js.strip():
            raise ContractError("the official meshctrl.js path is required")
        if not isinstance(login_user, str) or not login_user.strip():
            raise ContractError("the meshcentral login user is required")
        if not callable(password_provider):
            raise ContractError("the login password must be provided at call time")
        if not isinstance(url, str) or not url.startswith("wss://") or "@" in url:
            raise ContractError("the private tunnel URL must be a wss:// endpoint")
        self._run = command_runner
        self._meshctrl_js = meshctrl_js
        self._login_user = login_user
        self._password_provider = password_provider
        self._url = url
        self._work_dir = work_dir
        #: Which executor wrote a marker. The failover partner (#5462) can hold a
        #: claim on the same PC during a handover, and its running command is not
        #: this host's to clear, so a leftover is only "ours" when the tag matches.
        self._host_tag = (
            _checked_host_tag(host_tag) if host_tag is not None else _local_host_tag()
        )

    def run_command(
        self,
        *,
        node_ref: str,
        command: str,
        timeout_seconds: int | None = None,
        phase_observer: Callable[[str], None] | None = None,
        cancel_probe: Callable[[], bool] | None = None,
        dispatch_id: str | None = None,
        keep_dispatch_ids=(),
        line_guard: Callable[[], bool] | None = None,
        session_lane: bool | None = None,
        line_probe: bool | None = None,
    ) -> MeshCentralCommandOutcome:
        def phase(name: str) -> None:
            if callable(phase_observer):
                try:
                    phase_observer(name)
                except Exception:
                    # Instrumentation must never alter command execution.
                    pass

        def cancelled() -> bool:
            if cancel_probe is None:
                return False
            try:
                return cancel_probe() is True
            except Exception:
                # A probe that cannot be read is not an owner's stop. Refusing to
                # cancel on a transport problem is the only safe answer: the other
                # side of this choice ends a real command on a real PC.
                return False

        if cancel_probe is not None and not callable(cancel_probe):
            raise ContractError("the cancel probe must be callable")
        if line_guard is not None and not callable(line_guard):
            raise ContractError("the line guard must be callable")

        if not isinstance(node_ref, str) or not node_ref.strip():
            raise MeshCentralCommandRefused("node_ref is required")
        # Owner decision (#5895): a long-running command carries no PADIEM
        # client deadline by default, the way the desktop lane already runs
        # with None. An explicit timeout remains available and is a caller
        # choice, not a product ceiling, so it is only bounded below by one.
        if timeout_seconds is not None:
            if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int):
                raise MeshCentralCommandRefused("timeout_seconds must be an integer or None")
            if timeout_seconds < 1:
                raise MeshCentralCommandRefused("timeout_seconds is out of range")
        body = _bounded_command(command)
        # The marker is what makes a stop able to find this exact command on the
        # PC. Refusing a malformed id here is also the only thing standing between
        # a caller-supplied string and a PowerShell literal on a customer machine.
        checked_dispatch = None if dispatch_id is None else _checked_dispatch_id(dispatch_id)
        wrapped = _wrap(body, checked_dispatch, self._host_tag)
        # The NUL the C execve boundary appends is counted, so a refusal here
        # is the kernel's own limit, not a product rule. The aggregate argv and
        # environment ceiling depends on this host's stack rlimit and is not
        # guessed at; it is far above the row a dispatch can ever carry.
        if len(wrapped.encode("utf-8")) + 1 > _MAX_ARGV_ELEMENT_BYTES:
            raise MeshCentralCommandRefused(
                "the wrapped command exceeds the OS single-argument limit"
            )
        argv = [
            "node", "-e", _MESHCTRL_STDIN_BOOTSTRAP,
            self._meshctrl_js, "runcommand",
            "--url", self._url,
            "--loginuser", self._login_user,
            "--loginpass", "__PADIEM_MESHCTRL_PASSWORD_FROM_STDIN__",
            "--id", node_ref.strip(),
            "--powershell",
            "--run", wrapped,
            "--reply",
        ]
        password = self._password_provider()
        if not isinstance(password, str) or not password or "\n" in password or "\r" in password:
            raise MeshCentralCommandRefused(
                "the protected MeshCentral operator credential is invalid"
            )
        if self._popen_factory is None:
            # Buffered fallback for callers that only inject a command runner.
            phase("spawn")
            try:
                completed = self._run(
                    argv, input=password + "\n", timeout=timeout_seconds,
                )
            except Exception as exc:
                if type(exc).__name__ == "TimeoutExpired":
                    phase("timeout")
                    return MeshCentralCommandOutcome(
                        termination="timed_out", exit_code=None, output=b"",
                    )
                raise MeshCentralCommandRefused(
                    "the official meshcentral client failed"
                ) from exc
            if getattr(completed, "returncode", None) != 0:
                phase("reply")
                return MeshCentralCommandOutcome(
                    termination="no_reply", exit_code=None, output=b"",
                )
            raw = getattr(completed, "stdout", b"") or b""
            if isinstance(raw, str):
                raw = raw.encode("utf-8", errors="replace")
            outcome = self._from_transcript(raw)
            phase("reply")
            return outcome
        if checked_dispatch is not None and _session_lane_enabled(session_lane):
            # #82 standard 2: the command gets its own terminal session, so another
            # dispatch on this PC is never waiting behind it. No line sweep here - the
            # session is not the queue the sweep exists to unblock.
            phase("session_lane")
            session_outcome = self._run_command_on_a_session(
                node_ref=node_ref.strip(), command=body, dispatch_id=checked_dispatch,
                password=password, phase=phase, cancelled=cancelled,
                timeout_seconds=timeout_seconds,
            )
            if session_outcome is not None:
                return session_outcome
            # A session that never opened is not a failed command: send it the way the
            # lane has always sent it. Phase names which happened.
            phase("session_fallback")
        return self._stream_with_line_selfheal(
            argv, password, timeout_seconds, phase, cancelled,
            node_ref=node_ref.strip(), dispatch_id=checked_dispatch,
            keep_dispatch_ids=_keep_id_literals(checked_dispatch, keep_dispatch_ids),
            line_guard=line_guard,
            line_probe=line_probe,
        )

    def _run_command_on_a_session(
        self, *, node_ref: str, command: str, dispatch_id: str, password: str,
        phase: Callable[[str], None],
        cancelled: Callable[[], bool] | None,
        timeout_seconds: int | None,
    ) -> MeshCentralCommandOutcome | None:
        """One dispatch on its own terminal session; ``None`` when none opened.

        The agent serves N terminal tunnels per node with no cap and keeps each alive
        until it ends, which is the lane the owner standard 2 asks for: a command that
        takes minutes holds only itself.

        Two bounds, both on communication and neither on the work: how long the session
        may take to accept the script and answer anything (``SESSION_OPEN_TIMEOUT_SECONDS``),
        and an explicit caller deadline if one was given. After the first bytes the wait
        is the work's own, exactly as on the queue lane.

        MeshCentral's own limit is respected rather than invented: the agent closes the
        connection after 30 consecutive identical console output strings
        (``src/meshagent.js:1287-1295``), so nothing here repeats a payload at a cadence,
        and there is no PADIEM cap on how many sessions a PC may have.
        """
        import subprocess
        import time

        if self._popen_factory is None:
            return None
        argv = [
            "node", "-e", _MESHCTRL_STDIN_LINE_BOOTSTRAP,
            self._meshctrl_js, "shell",
            "--url", self._url,
            "--loginuser", self._login_user,
            "--loginpass", "__PADIEM_MESHCTRL_PASSWORD_FROM_STDIN__",
            "--id", node_ref,
            "--powershell",
        ]
        wrapped = _wrap(command, dispatch_id, self._host_tag, split_markers=True)
        try:
            handoff = self._pty_factory(
                (password + "\n" + wrapped + "\n").encode("utf-8"),
            )
        except Exception:
            phase("session_open_refused")
            return None
        child = self._popen_factory(
            argv, stdin=handoff.slave, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
        )
        buffer = bytearray()
        opened = time.monotonic()
        seen = False
        try:
            while True:
                chunk = handoff.read(1.0)
                if chunk:
                    seen = True
                    if len(buffer) < HANDOFF_CAPTURE_LIMIT:
                        buffer.extend(chunk)
                if _SENTINEL_LINE.search(bytes(buffer)):
                    break
                if child.poll() is not None:
                    break
                if not seen and time.monotonic() - opened > SESSION_OPEN_TIMEOUT_SECONDS:
                    phase("session_open_timeout")
                    return None
                if timeout_seconds is not None and time.monotonic() - opened > timeout_seconds:
                    phase("timeout")
                    return MeshCentralCommandOutcome(
                        termination="timed_out", exit_code=None, output=b"",
                    )
                if cancelled is not None and cancelled():
                    # Ending the session alone would leave the PC process running, so the
                    # owner's stop travels the same kill path the queue lane uses.
                    self._stop_on_pc(node_ref, dispatch_id, phase)
                    phase("cancel")
                    return MeshCentralCommandOutcome(
                        termination="cancelled", exit_code=None, output=b"",
                    )
        finally:
            try:
                if child.poll() is None:
                    child.kill()
            finally:
                handoff.close()
        raw = bytes(buffer)
        if not raw:
            # The session closed before it printed anything: no session opened, so the
            # caller may still send the command the old way.
            return None
        outcome = self._from_transcript(_session_payload(raw))
        phase("reply")
        return outcome

    # ---- streaming execution -------------------------------------------
    def _stream_with_line_selfheal(
        self, argv: list[str], password: str, timeout_seconds: int | None,
        phase: Callable[[str], None],
        cancelled: Callable[[], bool] | None,
        *,
        node_ref: str,
        dispatch_id: str | None,
        keep_dispatch_ids: tuple[str, ...],
        line_guard: Callable[[], bool] | None = None,
        line_probe: bool | None = None,
    ) -> MeshCentralCommandOutcome:
        """Run one command, and free the console line when something else holds it.

        Two waits are kept apart here because the owner rule keeps them apart: the
        work on the PC has no ceiling, while the wait for an answer does. The
        pre-flight sweep is what stops a leftover process from costing the
        ``LINE_STALL_WAIT_SECONDS`` detection at all, and the in-flight sweep is what
        catches a line that wedges while this command waits. One retry, because a
        second one would be a queue of guesses against a machine already answered
        once.
        """
        sweeps: list[MeshCentralLineSweep] = []
        # #6106/#6113 probe, off unless the operator says the shell lane executes.
        probe_enabled = _line_probe_enabled(line_probe)
        if probe_enabled and dispatch_id is not None:
            sweeps.append(self.sweep_agent_children(
                node_ref=node_ref, dispatch_id=dispatch_id,
                keep_dispatch_ids=keep_dispatch_ids,
                mode=SWEEP_MODE_ABANDONED, phase_observer=phase,
            ))
        # An explicit deadline already bounds the wait, so the line watch rides the
        # no-decision case only: it is the shape the operational lane actually uses.
        line_watch = (probe_enabled and timeout_seconds is None
                      and dispatch_id is not None)
        attempts = 0
        outcome: MeshCentralCommandOutcome | None = None
        while True:
            attempts += 1
            outcome, report = self._run_streaming(
                argv, password, timeout_seconds, phase, cancelled,
                node_ref=node_ref, dispatch_id=dispatch_id,
                keep_dispatch_ids=keep_dispatch_ids, line_watch=line_watch,
                line_guard=line_guard,
            )
            if report is None:
                break
            sweeps.append(report)
            if attempts >= 2:
                break
            phase("line_retry")
        blocked = sum(
            1 for sweep in sweeps
            if sweep.observed and not sweep.running and sweep.found
        )
        cleared = sum(len(sweep.killed) for sweep in sweeps)
        return MeshCentralCommandOutcome(
            termination=outcome.termination,
            exit_code=outcome.exit_code,
            output=outcome.output,
            method=outcome.method,
            merged_streams=outcome.merged_streams,
            line_blocked=blocked,
            line_cleared=cleared,
        )

    def _run_streaming(
        self, argv: list[str], password: str, timeout_seconds: int | None,
        phase: Callable[[str], None],
        cancelled: Callable[[], bool] | None = None,
        *,
        node_ref: str | None = None,
        dispatch_id: str | None = None,
        keep_dispatch_ids: tuple[str, ...] = (),
        line_watch: bool = False,
        line_guard: Callable[[], bool] | None = None,
    ) -> tuple[MeshCentralCommandOutcome, MeshCentralLineSweep | None]:
        """Read the child's transcript in chunks and return it whole.

        #5895: the transcript carries no PADIEM byte ceiling — the chunked
        read streams what the PC actually sent, and the whole transcript is
        returned. A ``timeout_seconds`` of None means no PADIEM client
        deadline (the desktop-lane default): the command runs until the console
        answers, and only an explicit timeout is killed at its deadline and
        reported as ``timed_out`` — the remote process may still be running, so
        no exit code is claimed.
        """
        import subprocess
        import time

        process = self._popen_factory(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        phase("spawn")
        chunks: list[bytes] = []
        #: When an answer-less wait becomes a line that is held by something else.
        #: Absolute, and pushed forward every time the PC proves the work is running.
        stall_at = time.monotonic() + LINE_STALL_WAIT_SECONDS
        try:
            if process.stdin is not None:
                process.stdin.write((password + "\n").encode("utf-8"))
                process.stdin.flush()
                process.stdin.close()
            deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds
            while True:
                if deadline is not None and time.monotonic() > deadline:
                    process.kill()
                    phase("timeout")
                    return MeshCentralCommandOutcome(
                        termination="timed_out", exit_code=None, output=b"",
                    ), None
                # None deadline: wait on the console with a fixed read slice so
                # the loop stays responsive to the child finishing.
                remaining = 1.0 if deadline is None else deadline - time.monotonic()
                if deadline is not None and remaining <= 0:
                    process.kill()
                    phase("timeout")
                    return MeshCentralCommandOutcome(
                        termination="timed_out", exit_code=None, output=b"",
                    ), None
                chunk = _read_some(process, max(0.05, min(1.0, remaining)))
                if not chunk:
                    if process.poll() is not None:
                        break
                    # The owner stopped this. Ending the client is the whole
                    # mechanism: it closes the MeshCentral session, so the command
                    # lane is free for the next operation instead of waiting on a
                    # console that may never answer (#5995 removed the deadline,
                    # and a silent PC held every later operation behind it).
                    if cancelled is not None and cancelled():
                        # Two ends, in this order: first ask the PC to stop the work
                        # it is running, then stop waiting here. Ending only the
                        # client left the customer's process running behind a
                        # serial console queue, which is what held every later
                        # operation on that PC after a stop (measured 2026-10-28).
                        self._stop_on_pc(node_ref, dispatch_id, phase)
                        process.kill()
                        phase("cancel")
                        return MeshCentralCommandOutcome(
                            termination="cancelled", exit_code=None, output=b"",
                        ), None
                    if line_watch and time.monotonic() >= stall_at:
                        stall_at = time.monotonic() + LINE_STALL_WAIT_SECONDS
                        if not _may_clear(line_guard, phase):
                            # Somebody's claim is live on this PC according to the
                            # server, so this silence belongs to real work that is
                            # not ours to end. Stop waiting on a request the agent
                            # already dropped, and let the caller's single retry ask
                            # again - without touching anything on the machine.
                            process.kill()
                            return MeshCentralCommandOutcome(
                                termination="no_reply", exit_code=None, output=b"",
                            ), MeshCentralLineSweep(
                                mode=SWEEP_MODE_HELD, ran=False, observed=False,
                                running=False, gated=True,
                                error="a live claim on this PC was not cleared",
                            )
                        report = self.sweep_agent_children(
                            node_ref=str(node_ref), dispatch_id=str(dispatch_id),
                            keep_dispatch_ids=keep_dispatch_ids,
                            mode=SWEEP_MODE_HELD, phase_observer=phase,
                        )
                        if report.running:
                            # The PC names this command's own process as alive. The
                            # wait is then a wait for the work, and the work carries
                            # no ceiling: ask again after another window, touch
                            # nothing.
                            continue
                        phase("line_stalled")
                        process.kill()
                        return MeshCentralCommandOutcome(
                            termination="no_reply", exit_code=None, output=b"",
                        ), report
                    continue
                chunks.append(chunk)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
            raise MeshCentralCommandRefused("the official meshcentral client failed") from None
        raw = b"".join(chunks)
        outcome = self._from_transcript(raw)
        phase("reply")
        return outcome, None

    def _stop_on_pc(
        self, node_ref: str | None, dispatch_id: str | None, phase: Callable[[str], None],
    ) -> bool:
        """End the stopped command on the PC, best effort, and say which happened.

        A failed stop is reported and never turns into a refusal here: the owner's
        stop has already been honoured on this host, and the row's own result is on
        its way. Silent failure is the thing to avoid, so the phase names it.
        """
        if node_ref is None or dispatch_id is None:
            return False
        try:
            self.kill_command_process(node_ref=node_ref, dispatch_id=dispatch_id)
        except Exception:
            phase("cancel_kill_refused")
            return False
        phase("cancel_kill")
        return True

    def _run_shell_session(
        self,
        node_ref: str,
        script: str,
        *,
        answer: Callable[[bytes], bool] | None = None,
        wait_seconds: float = CANCEL_KILL_WAIT_SECONDS,
    ) -> bytes:
        """One bounded command on the agent's terminal channel, never on its console.

        ``runcommand`` cannot carry either of these. The agent holds one global
        command child, and while that child lives a later ``runcommand`` is answered
        with "already busy" and dropped - it is not queued, so no amount of waiting
        produces an answer for it. ``meshctrl shell`` opens the agent's terminal as a
        tunnel instead, which is the channel that worked by hand on 2026-10-28 and
        2026-10-29 while that console was held. The session is bounded in both shapes,
        so an unreachable agent cannot turn a repair into the new way to hang a PC.
        """
        import subprocess

        if not isinstance(node_ref, str) or not node_ref.strip():
            raise MeshCentralCommandRefused("node_ref is required")
        if self._popen_factory is None:
            raise MeshCentralCommandRefused(
                "the agent's terminal channel needs the streaming client"
            )
        password = self._password_provider()
        if not isinstance(password, str) or not password or "\n" in password or "\r" in password:
            raise MeshCentralCommandRefused(
                "the protected MeshCentral operator credential is invalid"
            )
        argv = [
            "node", "-e", _MESHCTRL_STDIN_LINE_BOOTSTRAP,
            self._meshctrl_js, "shell",
            "--url", self._url,
            "--loginuser", self._login_user,
            "--loginpass", "__PADIEM_MESHCTRL_PASSWORD_FROM_STDIN__",
            "--id", node_ref.strip(),
            "--powershell",
        ]
        handoff = self._pty_factory(
            (password + "\n" + script + "\n").encode("utf-8"),
        )
        child = self._popen_factory(
            argv, stdin=handoff.slave, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
        )
        # The client is ended on every path out of this session, including a pump
        # that raised: an abandoned node process on this host would be exactly the
        # thing this whole lane exists to stop leaving behind on the PC.
        try:
            if answer is None:
                handoff.wait_closed(wait_seconds)
            else:
                return handoff.wait_for(answer, wait_seconds)
        finally:
            if child.poll() is None:
                child.kill()
        return b""

    def kill_command_process(self, *, node_ref: str, dispatch_id: str) -> None:
        """End exactly one dispatch's own process tree on the PC.

        ``runcommand`` cannot carry a stop: it is the queue the running command is
        holding. ``meshctrl shell`` opens the agent's terminal over its own session,
        which is the channel that worked by hand on 2026-10-28 while the queue was
        wedged. The command sent through it names only the stopped dispatch's pid
        marker - no image name, no service, no window title - and the whole session
        is bounded, so an unreachable agent cannot make this the new way to hang.
        """
        checked = _checked_dispatch_id(dispatch_id)
        self._run_shell_session(node_ref, cancel_kill_command(checked))

    def sweep_agent_children(
        self,
        *,
        node_ref: str,
        dispatch_id: str | None = None,
        keep_dispatch_ids=(),
        mode: str = SWEEP_MODE_ABANDONED,
        phase_observer: Callable[[str], None] | None = None,
    ) -> MeshCentralLineSweep:
        """Free the PC's console line from a process that no dispatch owns.

        The sweep always runs, and the decision to end anything is taken on the PC by
        ``sweep_script`` - so an answer that never comes back costs evidence, not a
        safety property. A refusal here is reported as ``ran=False`` and never raised
        into the command's own result: a PC that cannot be asked about its console is
        still a PC whose command must be sent.
        """
        def phase(name: str) -> None:
            if callable(phase_observer):
                try:
                    phase_observer(name)
                except Exception:
                    pass

        script = sweep_script(
            dispatch_id=dispatch_id, keep_dispatch_ids=keep_dispatch_ids,
            mode=mode, host_tag=self._host_tag,
        )
        phase("line_probe")
        try:
            raw = self._run_shell_session(
                node_ref, script,
                answer=lambda buf: parse_sweep_reply(buf) is not None,
                wait_seconds=LINE_SWEEP_WAIT_SECONDS,
            )
        except Exception:
            phase("line_probe_refused")
            return MeshCentralLineSweep(
                mode=mode, ran=False, observed=False, running=False,
                error="the terminal channel refused the sweep",
            )
        verdict = parse_sweep_reply(raw)
        if verdict is None:
            # The session ran; its answer did not come back. Say so instead of
            # calling an unreadable console a clean one.
            phase("line_probe_unobserved")
            return MeshCentralLineSweep(
                mode=mode, ran=True, observed=False, running=False,
                error="the sweep answer was not readable",
            )
        running = verdict.get("running") is True
        found = verdict.get("found")
        killed = verdict.get("killed")
        reports = tuple(
            entry for entry in (found if isinstance(found, list) else ())
            if isinstance(entry, dict)
        )
        ended = tuple(
            int(entry) for entry in (killed if isinstance(killed, list) else ())
            if str(entry).isdigit()
        )
        if ended:
            phase("line_cleared")
        elif running:
            phase("line_running")
        return MeshCentralLineSweep(
            mode=mode, ran=True, observed=True, running=running,
            found=reports, killed=ended,
        )

    def _from_transcript(self, raw: bytes) -> MeshCentralCommandOutcome:
        if not raw:
            return MeshCentralCommandOutcome(
                termination="no_reply", exit_code=None, output=b"",
            )
        termination, exit_code, output = parse_transcript(raw)
        try:
            output.decode("utf-8")
        except UnicodeDecodeError:
            raise MeshCentralCommandRefused(
                "the command output is not valid UTF-8 and is refused, never altered"
            ) from None
        return MeshCentralCommandOutcome(
            termination=termination, exit_code=exit_code, output=output,
        )


__all__ = [
    "ENVELOPE_PREFIX",
    "EXIT_SENTINEL",
    "LINE_STALL_WAIT_SECONDS",
    "LINE_SWEEP_WAIT_SECONDS",
    "MAX_COMMAND_BYTES",
    "MAX_TRANSCRIPT_BYTES",
    "MERGED_STREAMS",
    "METHOD_LABEL",
    "SWEEP_SENTINEL",
    "MeshCentralCliCommandPort",
    "MeshCentralCommandOutcome",
    "MeshCentralCommandRefused",
    "MeshCentralLineSweep",
    "cancel_kill_command",
    "parse_sweep_reply",
    "parse_transcript",
    "sweep_script",
]
