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
import secrets
import sys
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

from .contracts import ContractError
from . import local_agent_mesh_command_phases as phases
from .local_agent_meshcentral_envelope import (
    ENVELOPE_PREFIX,
    EXIT_SENTINEL,
    _session_payload,
    _unwrap_envelope,
    parse_transcript,
)
from .local_agent_meshcentral_pid_handshake import (
    parse_pid_handshake,
    pid_handshake_statement,
    strip_pid_handshake,
)
from .local_agent_meshcentral_private_reader import (
    _MESHCTRL_LOGINKEY_BOOTSTRAP,
    _MESHCTRL_STDIN_BOOTSTRAP,
    _MESHCTRL_STDIN_LINE_BOOTSTRAP,
)

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


class MeshCentralStopUnconfirmed(MeshCentralCommandRefused):
    """The stop was sent but the PC never showed it ran it.

    A terminal that echoes its input (measured 2026-10-29 on every agent generation)
    answers without executing anything, so an open session is not evidence. Reporting a
    stop as done on an unexecuted line is the one outcome this lane may not produce.

    `verdict` carries the process lane's own word for why - `no_target`, `still_running`,
    `lane_unanswered` - so a journal says which answer came back without repeating any
    part of a customer's process table.
    """

    def __init__(self, message: str, *, verdict: str | None = None) -> None:
        super().__init__(message)
        self.verdict = verdict


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
#: A result envelope is tagged with the dispatch it belongs to plus a value
#: generated fresh for that dispatch. Two dispatches can share a console buffer;
#: the tag is what makes the reader choose its own frame instead of the last one.
_ENVELOPE_TAG = re.compile(r"^dsp_[0-9a-f]{16,64}:[0-9a-f]{16,64}$")
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


def _checked_envelope_tag(value: Any) -> str:
    """A tag is this module's own correlation value, never customer text."""
    if not isinstance(value, str) or _ENVELOPE_TAG.fullmatch(value) is None:
        raise MeshCentralCommandRefused("the result envelope tag is not a dispatch tag")
    return value


def _envelope_tag(dispatch_id: str, token: str) -> str:
    """The dispatch id and the per-run value that only this result may carry."""
    checked = _checked_dispatch_id(dispatch_id)
    return _checked_envelope_tag(checked + ":" + token)


def _new_envelope_tag(dispatch_id: str) -> str:
    return _envelope_tag(dispatch_id, secrets.token_hex(16))


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

    #7564: the file is also evidence about WHO wrote it and WHICH process it
    named. A marker this lane did not write is skipped whole - the pid in it is
    never read as a target and the file is left alone. A marker this lane's
    account did write is read the way every version of this command has read it,
    with one addition: a marker that carries its process's start time (the
    three-line format) ends the tree only when the process at that pid still has
    that same start time, and a marker naming a process that started under that
    pid at another time is cleared without anything being ended, so a reused pid
    can never turn a stale marker into a kill.
    """
    marker = "$__padiem_stop"
    # The last line is the evidence that this script RAN: the marker line is split so
    # a terminal that only echoes its input can never produce the joined token.
    script = (
        "$ErrorActionPreference='SilentlyContinue';"
        + SWEEP_OWNER_SID_PS + ";"
        f"{marker}={_pid_file_literal(dispatch_id)};"
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
    if len(script.encode("utf-8")) >= TERMINAL_SCRIPT_BUDGET_BYTES:
        raise MeshCentralCommandRefused(
            "the stop script exceeds the terminal prequeue budget"
        )
    return script


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
#: How many bytes the terminal device holds for a client that has not attached its
#: reader yet. This side writes the whole session input before ``meshctrl`` reaches
#: the point where it installs one (`meshctrl.js:2892`, only after the tunnel says
#: connected), and Linux fixes that queue at N_TTY_BUF_SIZE = 4096
#: (`drivers/tty/n_tty.c`) - past it the tail is dropped without a word, which would
#: deliver half a script to a customer PC. A script that cannot fit is refused here.
TERMINAL_PREQUEUE_LIMIT_BYTES = 4096
#: #7564: who may author a dispatch marker. A marker in the agent's temp folder
#: names a process tree SYSTEM will end, so a file a different local account
#: dropped there must never be read as one. Owners are compared as SIDs, so a
#: localized account name cannot change the answer: ``S-1-5-18`` is LocalSystem
#: and ``S-1-5-32-544`` is the Administrators group. A marker with any other
#: owner is skipped whole - not read, not ended, not deleted.
TRUSTED_MARKER_SIDS = ("S-1-5-18", "S-1-5-32-544")
#: The PowerShell that reads one file's owner as a SID, '' when the ACL cannot be
#: read. ``GetOwner`` reads the raw owner SID out of the security descriptor, so
#: the answer never depends on the account name resolving (a localized or
#: orphaned owner name would otherwise read as no owner at all). Shared verbatim
#: by the stop, the sweep and their tests.
SWEEP_OWNER_SID_PS = (
    "function __padiemSid($p){try{"
    "(Get-Acl -LiteralPath $p).GetOwner"
    "([Security.Principal.SecurityIdentifier]).Value}catch{''}}"
)
#: #7564: the marker-orphan verdict, split out so tests can run it on real
#: PowerShell with made-up inputs. Inputs: ``$ms`` markers (@{id;pid;host;st;sid;file};
#: ``st`` is the process start time new markers carry, '' for the old two-line
#: format), ``$px`` the process table keyed by pid (@{pp;cr;nm}), ``$safe`` pids
#: never to end, ``$keep`` dispatch ids a live lane still owns, ``$tag`` this
#: host's tag, ``$reqHost`` whether a marker must name this host. One decision
#: per marker: ``kill`` (end that pid tree and clear the marker), ``clean`` (clear
#: the marker only - the process is gone, or a new-format marker names a process
#: that started under that pid at another time), ``skip`` (touch nothing).
SWEEP_MARKER_JUDGE_PS = (
    "function __padiemJudgeM($ms,$px,$safe,$keep,$tag){$o=@();foreach($__m in $ms){"
    "if($__m.sid -notin 'S-1-5-18','S-1-5-32-544'){"
    "$o+=@{act='skip';why='owner'};continue};"
    "if($keep -contains $__m.id){$o+=@{act='skip';why='keep'};continue};"
    "if(-not $__m.pid){$o+=@{act='skip';why='pid'};continue};"
    # A $null tag means this sweep cannot tell its own leftover from a failover
    # partner's, and ends nothing by marker at all - every comparison fails.
    "if(-not $tag -or $__m.host -ne $tag){$o+=@{act='skip';why='host'};continue};"
    "if($safe -contains $__m.pid){$o+=@{act='skip';why='safe'};continue};"
    "$__e=$px[$__m.pid];"
    "if(-not $__e){$o+=@{act='clean';why='gone';file=$__m.file};continue};"
    "if($__m.st -and [string]$__e.cr -ne $__m.st){"
    "$o+=@{act='clean';why='stale';file=$__m.file};continue};"
    "$o+=@{act='kill';pid=$__m.pid;file=$__m.file;dispatch=$__m.id;"
    "name=$__e.nm;created=$__e.cr}};$o}"
)
#: #7564: the agent-child verdict, split out the same way. Inputs: ``$px`` the
#: process table, ``$safe`` pids never to end, ``$claimed`` pids a marker names
#: (idle scope only), ``$now`` and ``$agentCr`` the sweep's clock and the
#: agent's own start time as file times, ``$minAgeTicks`` the idle age bound in
#: 100-ns ticks, ``$idle`` whether the idle scope's extra bounds apply. A pid is
#: a child only when its record names the agent as parent AND it started after
#: the agent did - a process that existed before the agent, whatever now owns
#: that pid, is never this lane's to end.
SWEEP_CHILD_JUDGE_PS = (
    "function __padiemJudgeK($px,$safe,$claimed,$now,$agentPid,$agentCr,$minAgeTicks,$idle){"
    "$o=@();foreach($k in $px.Keys){$__e=$px[$k];"
    "if($__e.pp -ne $agentPid){continue};"
    "if(-not $agentCr -or -not $__e.cr -or $__e.cr -le $agentCr){continue};"
    "if($safe -contains $k){continue};if($idle){"
    "if($claimed -contains $k){continue};"
    "if(($now - $__e.cr) -lt $minAgeTicks){continue};"
    "$b=$false;foreach($c in $px.Values){"
    "if($c.pp -eq $k -and $c.nm -ne 'conhost.exe'){$b=$true}};"
    "if($b){continue}};"
    "$o+=@{act='kill';pid=$k;name=$__e.nm;created=$__e.cr}};$o}"
)
#: The terminal queue carries the credential line and the script with no reader
#: attached yet, so the whole payload must stay under
#: ``TERMINAL_PREQUEUE_LIMIT_BYTES``. The builders keep this much of it for the
#: password line and the line endings and refuse a script that would not fit,
#: instead of letting half of one reach a customer PC.
TERMINAL_SCRIPT_BUDGET_BYTES = TERMINAL_PREQUEUE_LIMIT_BYTES - 256


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
#: The stale idle console (#7180, measured 2026-11-08): an agent's direct child a
#: lost dispatch left behind held the console for 19 hours — the agent drops
#: (never queues) a later runcommand, so one orphan silenced every PC command
#: for a day. This scope ends only processes matching ALL of: parent = the
#: agent, older than the configured age, whose own children are nothing but
#: conhost, while nothing of this connector's is live on the PC. It kills by
#: explicit process id, never by a name pattern.
SWEEP_MODE_IDLE_CONSOLE = "idle_console"
SWEEP_MODES = (SWEEP_MODE_ABANDONED, SWEEP_MODE_HELD, SWEEP_MODE_IDLE_CONSOLE)

#: The reaper's master switch: ON by default, the operator turns it off with
#: ``PADIEM_MESH_IDLE_CONSOLE_REAP=0`` — the inverse of the opt-in lanes above,
#: because an orphaned console is exactly the failure this exists to end.
IDLE_CONSOLE_REAP_ENV = "PADIEM_MESH_IDLE_CONSOLE_REAP"
#: How old a candidate console must be. Zero or less disables the reaper: an
#: age bound of zero cannot tell a wedged console from work that just started.
IDLE_CONSOLE_MIN_AGE_ENV = "PADIEM_MESH_IDLE_CONSOLE_MIN_AGE_SECONDS"
IDLE_CONSOLE_MIN_AGE_SECONDS_DEFAULT = 900


def _idle_console_reap_enabled(explicit: bool | None = None, environ=None) -> bool:
    if explicit is not None:
        return explicit is True
    source = os.environ if environ is None else environ
    return (source.get(IDLE_CONSOLE_REAP_ENV) or "").strip().lower() not in (
        "0", "false", "no", "off",
    )


def _idle_console_min_age_seconds(environ=None) -> int:
    source = os.environ if environ is None else environ
    raw = (source.get(IDLE_CONSOLE_MIN_AGE_ENV) or "").strip()
    if not raw:
        return IDLE_CONSOLE_MIN_AGE_SECONDS_DEFAULT
    try:
        value = int(raw)
    except ValueError:
        return IDLE_CONSOLE_MIN_AGE_SECONDS_DEFAULT
    return value if value > 0 else 0


def _sweep_head(dispatch_id: str | None, keep: list[str]) -> str:
    """The PowerShell prologue: one process snapshot, and the markers on this PC.

    Every decision below is made from the table taken here, so two verdicts in one
    run can never disagree about the same process. The scan reads a marker's owner
    before its contents, and every value it stores is a recorded OS fact - pid,
    parent, start time, name. No image name, service name, window title or output
    text is matched anywhere, so a verdict cannot be talked into firing by a string
    that happens to appear on the screen.

    #7564: the process table is read once (pid -> parent, start time as a file
    time, name), so every verdict below compares recorded facts against the same
    snapshot instead of asking the OS again per candidate. A marker whose owner
    is not an account this lane trusts is skipped before its contents are read -
    the temp folder it sits in is writable by every local account, so a file
    there is only a marker when the agent's own account wrote it.
    """
    own = (
        "$__live=$null;$own=$tp+'" + PC_CANCEL_PID_FILE_PREFIX + dispatch_id + ".pid';"
        "if($tr -contains (__padiemSid $own)){"
        "$__v=@(gc -LiteralPath $own -TotalCount 3);"
        "$op=[uint32]$__v[0];$ot=$__v[2];$r=$__px[$op];"
        "if($r -and (-not $ot -or $r.cr -eq $ot)){ $__live=$r } };"
    ) if dispatch_id is not None else ""
    return (
        "$ErrorActionPreference='SilentlyContinue';"
        "$s=[uint32]$PID;$__px=@{};"
        "gcim Win32_Process|%{$__px[$_.ProcessId]=@{pp=$_.ParentProcessId;"
        "cr=$_.CreationDate.ToFileTime();nm=$_.Name}};"
        "$__ag=$__px[$s].pp;$__agc=$__px[$__ag].cr;"
        "$__now=[DateTime]::Now.ToFileTime();"
        "$tr=@('S-1-5-18','S-1-5-32-544');"
        "$tp=[IO.Path]::GetTempPath();"
        "$tk=$env:SystemRoot+'"
        "\\System32\\taskkill.exe';"
        + SWEEP_OWNER_SID_PS +
        own +
        "$__keep=@(" + ",".join("'" + i + "'" for i in keep) + ");"
        "$__safe=@($s);$cl=@();$__ms=@();"
        # The agent is named by walking up from this session's own process, so the
        # family chain is protected whatever the agent put between itself and this
        # shell. A sweep that ended its own session would answer nothing, which is
        # the failure mode this whole lane exists to avoid.
        "$w=$s;$hop=0;while($w -and $hop -lt 8){$r=$__px[$w];"
        "if(-not $r.pp){break};"
        "$__safe+=$r.pp;$w=$r.pp;$hop++};"
        # Every command names itself in the agent's own temporary folder. Read the
        # folder: a marker this connector still owns protects that tree, and a
        # marker nobody owns is the orphan this sweep exists to find. A marker with
        # an owner outside the trusted accounts is skipped before its contents are
        # read, so a file another account dropped there is neither evidence nor a
        # target.
        "foreach($__f in gci -LiteralPath $tp -Filter '"
        + PC_CANCEL_PID_FILE_PREFIX + "*.pid'){"
        "$__os=__padiemSid $__f.FullName;"
        "if($tr -notcontains $__os){continue};"
        "$id=$__f.BaseName.Substring(" + str(_MARKER_PREFIX_LENGTH) + ");"
        "$__v=@(gc -LiteralPath $__f.FullName -TotalCount 3);"
        "$__p=0;$__p=[uint32]$__v[0];$cl+=$__p;"
        "if($__keep -contains $id){if($__p){$__safe+=$__p}}"
        "else{$__ms+=@{id=$id;pid=$__p;host=$__v[1];st=$__v[2];sid=$__os;"
        "file=$__f.FullName}}};"
        "$fd=@();$kl=@();"
    )


def _sweep_frame(mode: str) -> str:
    return (
        "$o=@{mode='" + mode + "';agent=$__ag;"
        "running=($null-ne$__live);"
        "found=$fd;killed=$kl}|ConvertTo-Json -Depth 5;"
        "('__PADIEM_'+'SWEEP__'+[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($o)))"
    )


def sweep_script(
    *,
    dispatch_id: str | None = None,
    keep_dispatch_ids=(),
    mode: str = SWEEP_MODE_ABANDONED,
    host_tag: str | None = None,
    min_age_seconds: int = IDLE_CONSOLE_MIN_AGE_SECONDS_DEFAULT,
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
    * an orphan marker is removed with its tree, and a marker that carries its
      process's start time ends a tree only when the process at that pid still
      has that start time - so the next sweep can never aim a stale process id
      at a process that was started later under that number;
    * a marker whose owner is not an account the agent's own lane trusts is
      never read as a marker at all (see ``TRUSTED_MARKER_SIDS``).

    The verdict comes back as one Base64 line. Only ASCII may cross that frame:
    a Korean process name in a UTF-8 reply frame is what MeshCentral drops, and a
    dropped frame is a PC that looks healthy while its answer is gone.
    """
    if mode not in SWEEP_MODES:
        raise MeshCentralCommandRefused("the sweep scope is not one this module knows")
    keep = _keep_id_literals(dispatch_id, keep_dispatch_ids)
    head = _sweep_head(dispatch_id, keep)
    tag = _checked_host_tag(host_tag) if host_tag else ""
    # A sweep that cannot name its own host passes $null: the judge's host
    # comparison then fails for every marker and the marker pass ends nothing,
    # exactly as this scope always behaved without a tag.
    tag_arg = "'" + tag + "'" if host_tag else "$null"
    checked_age = int(min_age_seconds)
    if mode == SWEEP_MODE_IDLE_CONSOLE and checked_age <= 0:
        raise MeshCentralCommandRefused("the idle-console age bound must be positive")
    min_age_ticks = checked_age * 10_000_000
    idle_flag = "$true" if mode == SWEEP_MODE_IDLE_CONSOLE else "$false"
    judges = SWEEP_MARKER_JUDGE_PS
    if mode == SWEEP_MODE_IDLE_CONSOLE:
        judges += SWEEP_CHILD_JUDGE_PS
    elif mode == SWEEP_MODE_HELD:
        judges = SWEEP_CHILD_JUDGE_PS
    # Each marker decision carries the pid, the marker path and the OS facts the
    # verdict journal reports; the judge below never ends anything itself - it
    # only says which marker is a kill, which is a bare cleanup and which is a
    # skip, and this body applies exactly what it said. A kill decision is the
    # verdict entry itself, so the journal reports what the judge decided.
    apply_marker = (
        "if($__d.act -eq 'kill'){$fd+=$__d;"
        "& $tk /T /F /PID $__d.pid|Out-Null;$kl+=$__d.pid};"
        "if($__d.act -ne 'skip'){Remove-Item -LiteralPath $__d.file}"
    )
    marker_pass = (
        "foreach($__d in (__padiemJudgeM $__ms $__px $__safe $__keep "
        + tag_arg + ")){" + apply_marker + "};"
    )
    children_call = (
        "foreach($__d in (__padiemJudgeK $__px $__safe $cl $__now $__ag"
        " $__agc " + str(min_age_ticks) + " " + idle_flag + ")){"
        "if($__d.act -eq 'kill'){$fd+=$__d;"
        "& $tk /T /F /PID $__d.pid|Out-Null;$kl+=$__d.pid}}"
    )
    if mode == SWEEP_MODE_ABANDONED:
        body = "if (-not $__live){" + marker_pass + "};"
    elif mode == SWEEP_MODE_IDLE_CONSOLE:
        body = "if (-not $__live){" + marker_pass + children_call + "};"
    else:
        body = (
            "if (-not $__live){" + children_call + ";"
            "foreach($o in $__ms){Remove-Item -LiteralPath $o.file}};"
        )
    script = head + judges + body + _sweep_frame(mode)
    if len(script.encode("utf-8")) >= TERMINAL_SCRIPT_BUDGET_BYTES:
        raise MeshCentralCommandRefused(
            "the sweep script exceeds the terminal prequeue budget"
        )
    return script


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


#: Opt-in for the agent's own process lane (#6227 memo): off is the shipped behaviour,
#: and the terminal stop below is what runs while it is off. The lane itself is
#: `local_agent_meshcentral_process_port`. The fields this lane needed to know about are
#: now observed (CGI-1, 2026-10-30) and the lane follows them; what is still missing is its
#: socket layer, which is the transport PR, so the flag has nothing to hand a stop to yet.
PROCESS_LANE_ENV = "PADIEM_MESH_PROCESS_LANE"


def _process_lane_enabled(explicit: bool | None, environ=None) -> bool:
    """Whether a stop is carried by the process lane rather than the terminal.

    Same rule as every other lane on this connector: default no, explicit yes, never
    enabled by absence.
    """
    if explicit is not None:
        return explicit is True
    source = os.environ if environ is None else environ
    return (source.get(PROCESS_LANE_ENV) or "").strip().lower() in ("1", "true", "yes", "on")


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


#: The silent-wait backstop (#7177, measured 2026-11-08). The work on the PC
#: carries no ceiling, but the wait for ANY answer must not be infinite: MeshCentral
#: answers a ``runcommand`` whose console is already held with "already busy" and
#: drops it — it is not queued — so a wedged console used to leave every later
#: command's client silent forever (the 11-07 20:05 outage: start and spawn journaled,
#: not one result for a day). The bound counts TOTAL silence: no byte from the
#: client at all. Any received byte — output, an error transcript, a progress
#: echo — restarts it, so a long command that talks stays unlimited and a command
#: that ends is returned the moment it ends. It touches nothing on the PC: the
#: client is ended on this host and the dispatch reports ``timed_out`` like any
#: other expired wait. 0 disables the bound, which is the operator's own choice.
SILENT_WAIT_ENV = "PADIEM_MESH_SILENT_WAIT_SECONDS"
SILENT_WAIT_SECONDS_DEFAULT = 600


def _silent_wait_seconds(explicit: float | None = None, environ=None) -> float:
    """The silent-wait bound in seconds, 0 = wait forever, default 600."""

    if explicit is not None:
        return float(explicit)
    source = os.environ if environ is None else environ
    raw = (source.get(SILENT_WAIT_ENV) or "").strip()
    if not raw:
        return float(SILENT_WAIT_SECONDS_DEFAULT)
    try:
        value = float(raw)
    except ValueError:
        return float(SILENT_WAIT_SECONDS_DEFAULT)
    return max(0.0, value)



#: The joined token the stop script prints when it actually ran.
STOP_EVIDENCE = "__PADIEM_KILL__"


def _may_clear(line_guard: Callable[[], bool] | None,
               phase: Callable[[str], None]) -> bool:
    """Whether a held console may be cleared, as the caller's authority answers.

    No guard at all is a clear "no": a port composed without the server's view of
    the PC cannot tell its own idle from its failover partner's running command, and
    guessing is the one thing that would end real work. A guard that raises, times
    out or answers anything other than ``True`` is the same "no".
    """
    if line_guard is None:
        phase(phases.LINE_GATE_CLOSED)
        return False
    try:
        allowed = line_guard() is True
    except Exception:
        allowed = False
    if not allowed:
        phase(phases.LINE_GATE_BUSY)
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
          split_markers: bool = False, envelope_tag: str | None = None,
          pid_token: str | None = None) -> str:
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
    dispatch's marker file - see ``cancel_kill_command``. The marker is three
    lines: the process id first, because that is all the stop has ever read and
    all it will read; this executor host's own tag second, which is what lets a
    console sweep tell its own leftover from the leftover of the failover partner
    that claimed the same PC during a handover - a distinction that has to exist
    before anything on a customer machine may be ended; and the process's own
    start time third (#7564), so a sweep or a stop can tell a live dispatch from
    a stale pid the OS handed to somebody else. Readers that predate the third
    line read the first two exactly as before, and a marker whose start time
    could not be read is written without it, which every reader treats as the
    old format. Without a dispatch id it is the same bytes as before, so nothing
    about a command's own result can change.
    """
    marks = ""
    clears = ""
    tag = ""
    if envelope_tag is not None:
        tag = _checked_envelope_tag(envelope_tag)
        if dispatch_id is not None and not tag.startswith(dispatch_id + ":"):
            raise MeshCentralCommandRefused("the envelope tag names another dispatch")
        tag += ":"
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
        marks += (
            " $__padiem_dt=(Get-CimInstance Win32_Process"
            ' -Filter "ProcessId=$PID").CreationDate;'
            " if ($__padiem_dt) { Add-Content -LiteralPath $__padiem_pidfile"
            " -Value $__padiem_dt.ToFileTime() -Encoding ascii };"
        )
        clears = (
            " if ($__padiem_pidfile) {"
            " Remove-Item -LiteralPath $__padiem_pidfile -Force -ErrorAction SilentlyContinue };"
        )
    return (
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
        " $__padiem=$null;" + ("" if pid_token is None else " " + pid_handshake_statement(pid_token)) + marks +
        " try { $__padiem=(& { " + command + " } 2>&1 | Out-String)"
        " } catch { $__padiem=($_ | Out-String) };" + clears +
        # A terminal session echoes the script the shell was handed. The markers are
        # assembled from two literals on that lane, so the echo can never contain the
        # joined token while the bytes the PC prints stay exactly the same.
        (
            ' Write-Output ("PADIEM_" + "B64=" + '
            + ('"' + tag + '" + ' if tag else '')
            + "[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes([string]$__padiem)));"
            ' Write-Output ("__PADIEM_" + "EXIT__" + $LASTEXITCODE)'
            if split_markers else
            ' Write-Output ("' + ENVELOPE_PREFIX + '" + '
            + ('"' + tag + '" + ' if tag else '')
            + "[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes([string]$__padiem)));"
            ' Write-Output ("' + EXIT_SENTINEL + '" + $LASTEXITCODE)'
        ) + "; [Console]::Out.Flush()"
    )


#: #7199: how a long multi-line client reaches the PC without stalling the console.
#: The agent runs a runcommand by writing the script to a ``powershell -command -``
#: console over an OPEN stdin and replying only when that PowerShell exits. A script
#: with a block that spans lines (the ``& { ... }`` the SYSTEM envelope uses, a
#: ``try``/``while`` body, a here-string) leaves the console's line parser waiting for
#: the block to close, and a single line past the console input limit is truncated
#: mid-token. Either way the console never returns, and because the agent serves one
#: command child at a time and drops every later runcommand as "already busy", one
#: stalled console silences all PC commands (measured 2026-11-07..08, ~19 hours). The
#: SYSTEM lane never hit this: its wrapped command is a single short line.
#:
#: ``_file_dispatch_console_script`` sends the console ONLY complete single-line
#: statements, none of them an open block and none past the chunk bound: it writes
#: this dispatch's marker first (the exact two-line format the stop and the reaper
#: read), rebuilds the real client from base64 chunks held in a session variable,
#: writes it to a temp ``.ps1`` with a UTF-8 BOM, and runs THAT file with ``-File`` -
#: the same invocation that already completes in 0.4-2.3s when the script is a file.
#: The output and exit code return through the identical envelope + sentinel the
#: SYSTEM lane uses, so ``parse_transcript`` reads a file-delivered reply unchanged.
#: Delivery never depends on console-input parsing again.
CONSOLE_CHUNK_CHARS = 1000
#: The dispatch's own staged script, beside its ``.pid`` marker, in the agent
#: account's temp folder. Named by the same dispatch id, so the marker's process
#: tree (which the stop kills with ``taskkill /T``) contains this ``-File`` child.
PC_DISPATCH_PS1_SUFFIX = ".ps1"


def _file_dispatch_console_script(
    inner: str,
    dispatch_id: str,
    host_tag: str | None,
    chunk_size: int = CONSOLE_CHUNK_CHARS,
    envelope_tag: str | None = None,
    pid_token: str | None = None,
) -> str:
    """The console lines that stage ``inner`` to a temp file and run it with ``-File``.

    Every element of the returned script is a complete statement on its own line and
    no line opens a block that the next line must close, so the agent's
    ``powershell -command -`` console executes each line as it arrives and the agent's
    appended ``exit`` always runs. ``chunk_size`` keeps each ``$__s+='...'`` line far
    below the 8191-char console input limit; a script up to this module's single-argv
    ceiling is carried as a handful of such lines.

    The envelope and the exit sentinel are emitted by runtime string joins
    (``'PADIEM_'+'B64='``), so no line of this script text ever contains the joined
    marker a transcript is scanned for - the same guard the wrapped lane uses.
    """
    checked = _checked_dispatch_id(dispatch_id)
    tag = ""
    if envelope_tag is not None:
        tag = _checked_envelope_tag(envelope_tag)
        if not tag.startswith(checked + ":"):
            raise MeshCentralCommandRefused("the envelope tag names another dispatch")
        tag += ":"
    b64 = base64.b64encode(inner.encode("utf-8")).decode("ascii")
    size = chunk_size if isinstance(chunk_size, int) and chunk_size > 0 else CONSOLE_CHUNK_CHARS
    chunks = [b64[i:i + size] for i in range(0, len(b64), size)] or [""]
    marker = _pid_file_literal(checked)
    ps1 = (
        "[IO.Path]::GetTempPath()+'" + PC_CANCEL_PID_FILE_PREFIX + checked
        + PC_DISPATCH_PS1_SUFFIX + "'"
    )
    lines = [
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8",
        "$ProgressPreference='SilentlyContinue'",
        "$ConfirmPreference='None'",
        (pid_handshake_statement(pid_token) if pid_token is not None else "$null"),
        "$__pp=" + marker,
        # The marker is written exactly as the wrapped lane writes it: the process id
        # first (all the stop ever reads), this executor host's tag second (what lets
        # the reaper tell its own leftover from the failover partner's), and the
        # process's own start time third (#7564) - so a sweep or a stop can tell a
        # live dispatch from a stale pid the OS handed to somebody else. The process
        # is this console PowerShell, and the -File child runs inside its tree, so
        # the stop's ``taskkill /T`` ends the child with it.
        "Set-Content -LiteralPath $__pp -Value $PID -Encoding ascii",
    ]
    if host_tag:
        lines.append(
            "Add-Content -LiteralPath $__pp -Value '"
            + _checked_host_tag(host_tag) + "' -Encoding ascii"
        )
    lines.append(
        "$__padiem_dt=(Get-CimInstance Win32_Process -Filter \"ProcessId=$PID\").CreationDate"
    )
    lines.append(
        "if ($__padiem_dt) { Add-Content -LiteralPath $__pp"
        " -Value $__padiem_dt.ToFileTime() -Encoding ascii }"
    )
    lines.append("$__fp=" + ps1)
    lines.append("$__s=''")
    for chunk in chunks:
        lines.append("$__s+='" + chunk + "'")
    lines.extend([
        "$__enc=New-Object System.Text.UTF8Encoding($true)",
        "[IO.File]::WriteAllText($__fp,[Text.Encoding]::UTF8.GetString("
        "[Convert]::FromBase64String($__s)),$__enc)",
        "$__o=''",
        "try { $__o=(& ($PSHOME+'\\powershell.exe') -NoProfile -NonInteractive"
        " -ExecutionPolicy Bypass -File $__fp 2>&1 | Out-String) }"
        " catch { $__o=($_ | Out-String) }",
        "$__ec=$LASTEXITCODE",
        "Remove-Item -LiteralPath $__fp -Force -ErrorAction SilentlyContinue",
        "Remove-Item -LiteralPath $__pp -Force -ErrorAction SilentlyContinue",
        "Write-Output ('PADIEM_'+'B64='+" + ("'" + tag + "'+" if tag else "")
        + "[Convert]::ToBase64String("
        "[Text.Encoding]::UTF8.GetBytes([string]$__o)))",
        "Write-Output ('__PADIEM_'+'EXIT__'+[string]$__ec)",
        "[Console]::Out.Flush()",
    ])
    return "\n".join(lines)



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



def _still_the_terminal(fd: int) -> None:
    """Make the terminal device answer only for the PC, not for itself.

    Two termios defaults faked an answer on this lane. ECHO sends every byte written
    to the master straight back to it, so the bytes this side queued - credential line
    and script line - came home as a reply that looked like the PC had spoken (the
    2026-10-29 measurement: a 71-byte mirror, one more byte typed returning two more
    observed). And ICRNL rewrites the carriage return the PC's console needs to submit
    a typed line into a line feed, so the far end received a line that never executed.
    Both are cleared before anything is written. Clearing ECHO also keeps the
    credential out of the bytes this side can ever report.
    """
    import termios

    attrs = termios.tcgetattr(fd)
    attrs[0] &= ~termios.ICRNL
    attrs[3] &= ~termios.ECHO
    termios.tcsetattr(fd, termios.TCSANOW, attrs)


def _terminal_payload(password: str | None, script: str) -> bytes:
    """The credential line, then the script line, submitted the way a console takes it.

    The queue this side writes into is line-oriented: the line feed is what delivers
    the bytes to the client. The console at the far end submits on a carriage return,
    and once the client is in raw mode nothing translates either one - so both, in
    that order, are written down. With key-file login no password line is written.
    """
    prefix = "" if not password else password + "\n"
    return (prefix + script + "\r\n").encode("utf-8")


class _TerminalHandoff:
    """The pty ``meshctrl shell`` insists on, with its input already queued.

    The client reads the credential from standard input and then pipes that same
    stream into the PC's terminal, so the password is one line and the command is
    the bytes after it, and closing the handle ends the session. ``setRawMode`` is
    not a function on a pipe, which is why a terminal device is needed at all.

    The device is quieted before anything is written (see ``_still_the_terminal``),
    and the client's own output is read from this same handle - it is the only place
    the PC's answer can appear.
    """

    def __init__(self, write_bytes: bytes) -> None:
        import pty

        self._master, self.slave = pty.openpty()
        if len(write_bytes) >= TERMINAL_PREQUEUE_LIMIT_BYTES:
            # The queue would drop the tail of it. Refuse instead of sending half a
            # script to a customer machine and calling the answer the PC never had
            # a chance to give a verdict about.
            os.close(self._master)
            os.close(self.slave)
            raise MeshCentralCommandRefused(
                "the terminal queue cannot carry this script"
            )
        self.received = bytearray()
        _still_the_terminal(self.slave)
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

    def release_slave(self) -> None:
        """Drop this process's copy of the device once the client holds it.

        The client owns the terminal from that moment on. Keeping a second handle
        open here would mean the master never sees the client's exit as the end of
        the stream, and every session would wait out its whole bound.
        """
        try:
            os.close(self.slave)
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
        process_lane: Any = None,
        process_lane_factory: Callable[[str], Any] | None = None,
        process_lane_enabled: bool | None = None,
        run_as_user: bool = False,
        run_as_user_only: bool = False,
        login_key_file: str | None = None,
    ) -> None:
        if not callable(command_runner):
            raise ContractError("meshcentral command requires an injected command runner")
        # #7065: the agent runs as a Windows service (LocalSystem) unless the run is
        # asked for the signed-in user. Default off keeps today's argv byte-for-byte;
        # a deployment opts in through the environment below.
        #
        # Measured limit, stated so nobody reads an enabled flag as a promise:
        # MeshCentral's own issue tracker records that on Windows "run as user" is
        # ignored and the command still runs as ``nt authority\system``
        # (Ylianst/MeshCentral#4949, #6430). The flag is passed through as the client
        # documents it (``--runasuser``: try the logged-in user, fall back to the
        # agent; ``--runasuseronly``: refuse if that is impossible); whether the PC
        # honours it is the agent's answer, not this module's claim.
        if not isinstance(run_as_user, bool) or not isinstance(run_as_user_only, bool):
            raise ContractError("the run-as-user flags must be booleans")
        self._run_as_user = run_as_user or run_as_user_only
        self._run_as_user_only = run_as_user_only
        # The agent's own process verbs, when a deployment supplies the socket for them
        # (`local_agent_meshcentral_process_port`). None, or the flag off, means the
        # terminal stop below is what runs - which is today's shipped behaviour.
        if process_lane is not None and not hasattr(process_lane, "stop"):
            raise ContractError("the process lane needs a stop")
        if process_lane_factory is not None and not callable(process_lane_factory):
            raise ContractError("the process lane factory must be callable")
        self._process_lane = process_lane
        self._process_lane_factory = process_lane_factory
        self._process_lane_enabled = process_lane_enabled
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
        if login_key_file is not None and (
            not isinstance(login_key_file, str) or not login_key_file.strip()
        ):
            raise ContractError("the MeshCentral login-key file must be a path")
        if not isinstance(url, str) or not url.startswith("wss://") or "@" in url:
            raise ContractError("the private tunnel URL must be a wss:// endpoint")
        self._run = command_runner
        self._meshctrl_js = meshctrl_js
        self._login_user = login_user
        self._password_provider = password_provider
        self._login_key_file = login_key_file
        self._url = url
        self._work_dir = work_dir
        #: Which executor wrote a marker. The failover partner (#5462) can hold a
        #: claim on the same PC during a handover, and its running command is not
        #: this host's to clear, so a leftover is only "ours" when the tag matches.
        self._host_tag = (
            _checked_host_tag(host_tag) if host_tag is not None else _local_host_tag()
        )

    def _uses_login_key_file(self) -> bool:
        key_file = getattr(self, "_login_key_file", None)
        return isinstance(key_file, str) and bool(key_file.strip())

    def _runcommand_bootstrap(self) -> str:
        return _MESHCTRL_LOGINKEY_BOOTSTRAP if self._uses_login_key_file() else _MESHCTRL_STDIN_BOOTSTRAP

    def _shell_bootstrap(self) -> str:
        return _MESHCTRL_LOGINKEY_BOOTSTRAP if self._uses_login_key_file() else _MESHCTRL_STDIN_LINE_BOOTSTRAP

    def _login_argv(self) -> list[str]:
        if self._uses_login_key_file():
            return ["--loginkeyfile", self._login_key_file.strip()]
        return ["--loginpass", "__PADIEM_MESHCTRL_PASSWORD_FROM_STDIN__"]

    def _login_input(self) -> tuple[str | None, str | None]:
        if self._uses_login_key_file():
            return None, None
        password = self._password_provider()
        if not isinstance(password, str) or not password or "\n" in password or "\r" in password:
            raise MeshCentralCommandRefused(
                "the protected MeshCentral operator credential is invalid"
            )
        return password, password + "\n"

    def _terminal_password(self, password: str | None) -> str:
        if self._uses_login_key_file():
            return ""
        return password or ""

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
        deliver_as_file: bool = False,
        console_chunk_chars: int | None = None,
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
        # Every command carries a tag, including the read lane's guard and single
        # round trip that run without a dispatch marker: an untagged reply could
        # otherwise be taken from another PC's frame. Those get a one-off id that
        # only names the envelope, never a marker file.
        envelope_tag = _new_envelope_tag(
            checked_dispatch if checked_dispatch is not None
            else "dsp_" + secrets.token_hex(16)
        )
        pid_token = secrets.token_hex(8) if checked_dispatch is not None else None
        if deliver_as_file:
            # #7199: a long multi-line client is staged to a temp file and run with
            # ``-File`` so the agent's console never parses the client body as stdin.
            # The marker lives inside the staging script, so this lane always needs a
            # dispatch id (which the user-mode caller always has) and never routes to
            # the terminal-session lane, whose own wrapping would reopen the block.
            if checked_dispatch is None:
                raise MeshCentralCommandRefused(
                    "file delivery requires a dispatch id for its marker"
                )
            wrapped = _file_dispatch_console_script(
                body, checked_dispatch, self._host_tag,
                chunk_size=(console_chunk_chars or CONSOLE_CHUNK_CHARS),
                envelope_tag=envelope_tag, pid_token=pid_token,
            )
        else:
            wrapped = _wrap(
                body, checked_dispatch, self._host_tag,
                envelope_tag=envelope_tag, pid_token=pid_token,
            )
        # The NUL the C execve boundary appends is counted, so a refusal here
        # is the kernel's own limit, not a product rule. The aggregate argv and
        # environment ceiling depends on this host's stack rlimit and is not
        # guessed at; it is far above the row a dispatch can ever carry.
        if len(wrapped.encode("utf-8")) + 1 > _MAX_ARGV_ELEMENT_BYTES:
            raise MeshCentralCommandRefused(
                "the wrapped command exceeds the OS single-argument limit"
            )
        argv = [
            "node", "-e", self._runcommand_bootstrap(),
            self._meshctrl_js, "runcommand",
            "--url", self._url,
            "--loginuser", self._login_user,
        ]
        argv.extend(self._login_argv())
        argv.extend([
            "--id", node_ref.strip(),
            "--powershell",
            "--run", wrapped,
        ])
        # #7065. The envelope below is PowerShell text, so ``--powershell`` is not a
        # caller choice: the ``shell`` a tool asks for (powershell/cmd/bash) is
        # carried INSIDE that text as ``$env:PADIEM_MCP_SHELL`` plus the launcher
        # lines the shared table resolved at build time
        # (``padiem_ai_core.pc_shell_selection``); since #7188 R4 ② the script
        # itself no longer branches on the name. Dropping this flag would hand
        # PowerShell syntax to cmd.exe and break every command.
        if self._run_as_user:
            argv.append("--runasuser")
        if self._run_as_user_only:
            argv.append("--runasuseronly")
        argv.append("--reply")
        password, login_input = self._login_input()
        if self._popen_factory is None:
            # Buffered fallback for callers that only inject a command runner.
            phase(phases.SPAWN)
            try:
                completed = self._run(
                    argv, input=login_input, timeout=timeout_seconds,
                )
            except Exception as exc:
                if type(exc).__name__ == "TimeoutExpired":
                    phase(phases.TIMEOUT)
                    return MeshCentralCommandOutcome(
                        termination="timed_out", exit_code=None, output=b"",
                    )
                raise MeshCentralCommandRefused(
                    "the official meshcentral client failed"
                ) from exc
            if getattr(completed, "returncode", None) != 0:
                phase(phases.REPLY)
                return MeshCentralCommandOutcome(
                    termination="no_reply", exit_code=None, output=b"",
                )
            raw = getattr(completed, "stdout", b"") or b""
            if isinstance(raw, str):
                raw = raw.encode("utf-8", errors="replace")
            outcome = self._from_transcript(raw, envelope_tag)
            phase(phases.REPLY)
            return outcome
        if checked_dispatch is not None and not deliver_as_file and _session_lane_enabled(session_lane):
            # #82 standard 2: the command gets its own terminal session, so another
            # dispatch on this PC is never waiting behind it. No line sweep here - the
            # session is not the queue the sweep exists to unblock.
            phase(phases.SESSION_LANE)
            session_outcome = self._run_command_on_a_session(
                node_ref=node_ref.strip(), command=body, dispatch_id=checked_dispatch,
                envelope_tag=envelope_tag, pid_token=pid_token, password=password,
                phase=phase, cancelled=cancelled, timeout_seconds=timeout_seconds,
            )
            if session_outcome is not None:
                return session_outcome
            # A session that never opened is not a failed command: send it the way the
            # lane has always sent it. Phase names which happened.
            phase(phases.SESSION_FALLBACK)
        return self._stream_with_line_selfheal(
            argv, password, timeout_seconds, phase, cancelled,
            node_ref=node_ref.strip(), dispatch_id=checked_dispatch,
            envelope_tag=envelope_tag, pid_token=pid_token,
            keep_dispatch_ids=_keep_id_literals(checked_dispatch, keep_dispatch_ids),
            line_guard=line_guard,
            line_probe=line_probe,
        )

    def _run_command_on_a_session(
        self, *, node_ref: str, command: str, dispatch_id: str,
        envelope_tag: str | None, pid_token: str | None, password: str,
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
        import time

        if self._popen_factory is None:
            return None
        argv = [
            "node", "-e", self._shell_bootstrap(),
            self._meshctrl_js, "shell",
            "--url", self._url,
            "--loginuser", self._login_user,
        ]
        argv.extend(self._login_argv())
        argv.extend([
            "--id", node_ref,
            "--powershell",
        ])
        wrapped = _wrap(
            command, dispatch_id, self._host_tag, split_markers=True,
            envelope_tag=envelope_tag, pid_token=pid_token,
        )
        try:
            handoff = self._pty_factory(
                _terminal_payload(self._terminal_password(password), wrapped),
            )
        except Exception:
            phase(phases.SESSION_OPEN_REFUSED)
            return None
        child = self._popen_factory(
            argv, stdin=handoff.slave, stdout=handoff.slave, stderr=handoff.slave,
        )
        handoff.release_slave()
        buffer = bytearray()
        recorded_pid: int | None = None
        opened = time.monotonic()
        seen = False
        try:
            while True:
                chunk = handoff.read(1.0)
                if chunk:
                    seen = True
                    if len(buffer) < HANDOFF_CAPTURE_LIMIT:
                        buffer.extend(chunk)
                    if pid_token is not None and recorded_pid is None:
                        recorded_pid = parse_pid_handshake(bytes(buffer), pid_token)
                if _SENTINEL_LINE.search(bytes(buffer)):
                    break
                if child.poll() is not None:
                    break
                if not seen and time.monotonic() - opened > SESSION_OPEN_TIMEOUT_SECONDS:
                    phase(phases.SESSION_OPEN_TIMEOUT)
                    return None
                if timeout_seconds is not None and time.monotonic() - opened > timeout_seconds:
                    phase(phases.TIMEOUT)
                    return MeshCentralCommandOutcome(
                        termination="timed_out", exit_code=None, output=b"",
                    )
                if cancelled is not None and cancelled():
                    # Ending the session alone would leave the PC process running, so the
                    # owner's stop travels the same kill path the queue lane uses.
                    self._stop_on_pc(
                        node_ref, dispatch_id, phase, recorded_pid=recorded_pid,
                    )
                    phase(phases.CANCEL)
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
        if pid_token is not None:
            raw = strip_pid_handshake(raw, pid_token)
        if not raw:
            # The session closed before it printed anything: no session opened, so the
            # caller may still send the command the old way.
            return None
        payload = _session_payload(raw, envelope_tag)
        # If this command's own frame is absent, hand the raw buffer to the
        # tagged parser: it refuses it and journals the rejection. The raw bytes
        # still cannot become output because every strict path returns b"".
        outcome = self._from_transcript(payload or raw, envelope_tag)
        phase(phases.REPLY)
        return outcome

    # ---- streaming execution -------------------------------------------
    def _stream_with_line_selfheal(
        self, argv: list[str], password: str, timeout_seconds: int | None,
        phase: Callable[[str], None],
        cancelled: Callable[[], bool] | None,
        *,
        node_ref: str,
        dispatch_id: str | None,
        envelope_tag: str | None = None,
        keep_dispatch_ids: tuple[str, ...],
        pid_token: str | None = None,
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
                envelope_tag=envelope_tag,
                keep_dispatch_ids=keep_dispatch_ids, line_watch=line_watch,
                pid_token=pid_token, line_guard=line_guard,
            )
            if report is None:
                break
            sweeps.append(report)
            if attempts >= 2:
                break
            phase(phases.LINE_RETRY)
        # #7180: an expired wait on a PC whose answer never came is the shape a
        # lost dispatch's orphan console produces (measured 2026-11-08: one idle
        # agent child silenced every PC command for 19 hours). The reaper ends
        # exactly that process — agent's direct child, older than the age bound,
        # conhost-only children, nothing of ours live — and it rides every
        # timed_out completion of this wait, so the silent-wait bound reports the
        # outage AND the lane actually frees.
        if outcome.termination == "timed_out":
            self._reap_idle_console(
                node_ref=node_ref, dispatch_id=dispatch_id,
                keep_dispatch_ids=keep_dispatch_ids, phase=phase,
            )
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

    def _reap_idle_console(
        self, *, node_ref: str, dispatch_id: str | None,
        keep_dispatch_ids: tuple[str, ...],
        phase: Callable[[str], None],
    ) -> None:
        """End one stale idle console the lost dispatch left behind (#7180).

        Strictly an aside to the command's own outcome: default on, and the
        operator turns it off with ``PADIEM_MESH_IDLE_CONSOLE_REAP=0``. The
        decision of WHAT to end is taken on the PC by ``sweep_script`` — an
        agent's direct child, older than
        ``PADIEM_MESH_IDLE_CONSOLE_MIN_AGE_SECONDS`` (default 900), whose own
        children are nothing but conhost, while no dispatch of this connector's
        is live on the PC. Killed by explicit process id; the pid and the
        creation timestamp reach this host's journal, never a name pattern or
        an output value.
        """
        if not _idle_console_reap_enabled():
            return
        min_age = _idle_console_min_age_seconds()
        if min_age <= 0:
            return
        if not node_ref:
            return
        phase(phases.IDLE_REAP)
        try:
            report = self.sweep_agent_children(
                node_ref=node_ref, dispatch_id=dispatch_id,
                keep_dispatch_ids=keep_dispatch_ids,
                mode=SWEEP_MODE_IDLE_CONSOLE, phase_observer=phase,
                min_age_seconds=min_age,
            )
        except Exception:
            phase(phases.IDLE_REAP_REFUSED)
            return
        if report.killed:
            # OS facts only: pids and creation timestamps, capped so a strange
            # PC can never turn the journal into a stream.
            entries = report.found[:8]
            print(
                "pc_idle_console_reap killed=%d %s"
                % (len(report.killed), " ".join(
                    "pid=%s created=%s" % (entry.get("pid"), entry.get("created"))
                    for entry in entries if isinstance(entry, dict))),
                file=sys.stderr, flush=True,
            )
            phase(phases.IDLE_REAP_CLEARED)

    def _run_streaming(
        self, argv: list[str], password: str, timeout_seconds: int | None,
        phase: Callable[[str], None],
        cancelled: Callable[[], bool] | None = None,
        *,
        node_ref: str | None = None,
        dispatch_id: str | None = None,
        envelope_tag: str | None = None,
        keep_dispatch_ids: tuple[str, ...] = (),
        pid_token: str | None = None,
        line_watch: bool = False,
        line_guard: Callable[[], bool] | None = None,
        silent_wait_seconds: float | None = None,
    ) -> tuple[MeshCentralCommandOutcome, MeshCentralLineSweep | None]:
        """Read the child's transcript in chunks and return it whole.

        #5895: the transcript carries no PADIEM byte ceiling — the chunked
        read streams what the PC actually sent, and the whole transcript is
        returned. A ``timeout_seconds`` of None means no PADIEM client
        deadline (the desktop-lane default): the command runs until the console
        answers, and only an explicit timeout is killed at its deadline and
        reported as ``timed_out`` — the remote process may still be running, so
        no exit code is claimed.

        #7177: no deadline still does not mean an infinite silent wait. A client
        that has produced no byte at all for ``PADIEM_MESH_SILENT_WAIT_SECONDS``
        (default 600, 0 = wait forever) is ended here and reported ``timed_out``:
        MeshCentral drops — never queues — a ``runcommand`` whose console is
        already held, so the silence is the wedge itself. Every received byte
        restarts the bound, so a talking command stays unlimited.
        """
        import subprocess
        import time

        process = self._popen_factory(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        phase(phases.SPAWN)
        chunks: list[bytes] = []
        recorded_pid: int | None = None
        #: When an answer-less wait becomes a line that is held by something else.
        #: Absolute, and pushed forward every time the PC proves the work is running.
        stall_at = time.monotonic() + LINE_STALL_WAIT_SECONDS
        silent_bound = _silent_wait_seconds(silent_wait_seconds)
        #: Total silence so far: any byte from the client restarts this clock.
        last_byte_at = time.monotonic()
        try:
            if process.stdin is not None:
                process.stdin.write((password + "\n").encode("utf-8"))
                process.stdin.flush()
                process.stdin.close()
            deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds
            while True:
                if deadline is not None and time.monotonic() > deadline:
                    process.kill()
                    phase(phases.TIMEOUT)
                    return MeshCentralCommandOutcome(
                        termination="timed_out", exit_code=None, output=b"",
                    ), None
                # None deadline: wait on the console with a fixed read slice so
                # the loop stays responsive to the child finishing.
                remaining = 1.0 if deadline is None else deadline - time.monotonic()
                if deadline is not None and remaining <= 0:
                    process.kill()
                    phase(phases.TIMEOUT)
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
                        self._stop_on_pc(
                            node_ref, dispatch_id, phase, recorded_pid=recorded_pid,
                        )
                        process.kill()
                        phase(phases.CANCEL)
                        return MeshCentralCommandOutcome(
                            termination="cancelled", exit_code=None, output=b"",
                        ), None
                    # #7177: a client that never said anything is not work — work
                    # talks (the helper's stage-2 lane heartbeats every five
                    # seconds). End the client here, on this host, and let the
                    # dispatch complete; the owner's stop and the sweep remain the
                    # PC-side paths.
                    if silent_bound > 0 and time.monotonic() - last_byte_at >= silent_bound:
                        process.kill()
                        phase(phases.SILENT_TIMEOUT)
                        return MeshCentralCommandOutcome(
                            termination="timed_out", exit_code=None, output=b"",
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
                        phase(phases.LINE_STALLED)
                        process.kill()
                        return MeshCentralCommandOutcome(
                            termination="no_reply", exit_code=None, output=b"",
                        ), report
                    continue
                chunks.append(chunk)
                if pid_token is not None and recorded_pid is None:
                    recorded_pid = parse_pid_handshake(b"".join(chunks), pid_token)
                # A byte arrived: the client is talking, the bound restarts.
                last_byte_at = time.monotonic()
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
            raise MeshCentralCommandRefused("the official meshcentral client failed") from None
        raw = b"".join(chunks)
        if pid_token is not None:
            raw = strip_pid_handshake(raw, pid_token)
        outcome = self._from_transcript(raw, envelope_tag)
        phase(phases.REPLY)
        return outcome, None

    def _stop_on_pc(
        self, node_ref: str | None, dispatch_id: str | None, phase: Callable[[str], None],
        recorded_pid: int | None = None,
    ) -> bool:
        """End the stopped command on the PC, best effort, and say which happened.

        A failed stop is reported and never turns into a refusal here: the owner's
        stop has already been honoured on this host, and the row's own result is on
        its way. Silent failure is the thing to avoid, so the phase names it.
        """
        if node_ref is None or dispatch_id is None:
            return False
        try:
            self.kill_command_process(
                node_ref=node_ref, dispatch_id=dispatch_id, recorded_pid=recorded_pid,
            )
        except MeshCentralStopUnconfirmed as exc:
            if getattr(exc, "verdict", None):
                # Which answer came back, in our own words and never the PC's.
                phase(phases.CANCEL_KILL_PREFIX + str(exc.verdict))
            phase(phases.CANCEL_KILL_UNVERIFIED)
            return False
        except Exception:
            phase(phases.CANCEL_KILL_REFUSED)
            return False
        phase(phases.CANCEL_KILL)
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
        2026-10-29 while that console was held - an operator typing into a real
        terminal. What did not work was this side's scripted handoff, and the reason
        is in ``_TerminalHandoff``: the client answers on standard output, which used
        to be discarded here. The session is bounded in both shapes, so an unreachable
        agent cannot turn a repair into the new way to hang a PC.
        """
        if not isinstance(node_ref, str) or not node_ref.strip():
            raise MeshCentralCommandRefused("node_ref is required")
        if self._popen_factory is None:
            raise MeshCentralCommandRefused(
                "the agent's terminal channel needs the streaming client"
            )
        password, _ = self._login_input()
        argv = [
            "node", "-e", self._shell_bootstrap(),
            self._meshctrl_js, "shell",
            "--url", self._url,
            "--loginuser", self._login_user,
        ]
        argv.extend(self._login_argv())
        argv.extend([
            "--id", node_ref.strip(),
            "--powershell",
        ])
        handoff = self._pty_factory(
            _terminal_payload(self._terminal_password(password), script),
        )
        child = self._popen_factory(
            argv, stdin=handoff.slave, stdout=handoff.slave, stderr=handoff.slave,
        )
        handoff.release_slave()
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

    def kill_command_process(self, *, node_ref: str, dispatch_id: str,
                             recorded_pid: int | None = None) -> None:
        """End exactly one dispatch's own process on the PC.

        ``runcommand`` cannot carry a stop: it is the queue the running command is
        holding. ``meshctrl shell`` opens the agent's terminal over its own session,
        which is the channel that worked by hand on 2026-10-28 while the queue was
        wedged. The command sent through it names only the stopped dispatch's pid
        marker - no image name, no service, no window title - and the whole session
        is bounded, so an unreachable agent cannot make this the new way to hang.

        ``recorded_pid`` is the wrapper pid printed before the body; with the observed agent
        - whose records carry no parent field - it is the one authority a stop has for which
        process was ours. The marker file remains the terminal fallback's authority.
        """
        checked = _checked_dispatch_id(dispatch_id)
        lane = self._process_lane
        verdict: str | None = None
        if self._process_lane_factory is not None:
            try:
                lane = self._process_lane_factory(node_ref)
            except Exception:
                lane = None
        if lane is not None and _process_lane_enabled(self._process_lane_enabled):
            # The agent's own verbs: read the table, end the pid this dispatch recorded
            # (or, with no recorded pid, the pid whose record names our marker), read the
            # table again. The second read is the whole verdict - `pskill` answers nothing
            # of its own (agents/meshcore.js:1542-1550), so a sent frame is never evidence
            # that a process went away.
            try:
                report = lane.stop(checked, recorded_pid)
            except Exception:
                report = None
            if report is not None:
                if report.confirmed:
                    return
                verdict = getattr(report, "verdict", None)
            # A lane that cannot answer falls through to the terminal. The stop is
            # already bounded by both carriers; two bounded failures stay under the
            # one-minute target and never become a queue of attempts.
        raw = self._run_shell_session(
            node_ref, cancel_kill_command(checked),
            answer=lambda buf: STOP_EVIDENCE.encode("ascii") in buf,
            wait_seconds=CANCEL_KILL_WAIT_SECONDS,
        )
        if STOP_EVIDENCE.encode("ascii") not in (raw or b""):
            # The session answered nothing that proves the script ran. On 2026-10-29
            # every agent generation echoed input instead of executing it, so this is
            # the ordinary case until the transport is fixed.
            raise MeshCentralStopUnconfirmed(
                "the stop was not confirmed by the PC", verdict=verdict,
            )

    def sweep_agent_children(
        self,
        *,
        node_ref: str,
        dispatch_id: str | None = None,
        keep_dispatch_ids=(),
        mode: str = SWEEP_MODE_ABANDONED,
        phase_observer: Callable[[str], None] | None = None,
        min_age_seconds: int = IDLE_CONSOLE_MIN_AGE_SECONDS_DEFAULT,
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
            min_age_seconds=min_age_seconds,
        )
        phase(phases.LINE_PROBE)
        try:
            raw = self._run_shell_session(
                node_ref, script,
                answer=lambda buf: parse_sweep_reply(buf) is not None,
                wait_seconds=LINE_SWEEP_WAIT_SECONDS,
            )
        except Exception:
            phase(phases.LINE_PROBE_REFUSED)
            return MeshCentralLineSweep(
                mode=mode, ran=False, observed=False, running=False,
                error="the terminal channel refused the sweep",
            )
        verdict = parse_sweep_reply(raw)
        if verdict is None:
            # The session ran; its answer did not come back. Say so instead of
            # calling an unreadable console a clean one.
            phase(phases.LINE_PROBE_UNOBSERVED)
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
            phase(phases.LINE_CLEARED)
        elif running:
            phase(phases.LINE_RUNNING)
        return MeshCentralLineSweep(
            mode=mode, ran=True, observed=True, running=running,
            found=reports, killed=ended,
        )

    def _from_transcript(
        self, raw: bytes, envelope_tag: str | None = None,
    ) -> MeshCentralCommandOutcome:
        if not raw:
            return MeshCentralCommandOutcome(
                termination="no_reply", exit_code=None, output=b"",
            )
        termination, exit_code, output = parse_transcript(raw, envelope_tag)
        if envelope_tag is not None and termination in ("bad_reply", "no_reply"):
            # The tag itself is a correlation value, so only the dispatch prefix
            # and the verdict travel; the frame is discarded, never shown.
            print(
                "pc_envelope_rejected dispatch=%s reason=tag_missing_or_mismatch"
                % envelope_tag.split(":", 1)[0][:16],
                file=sys.stderr, flush=True,
            )
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
