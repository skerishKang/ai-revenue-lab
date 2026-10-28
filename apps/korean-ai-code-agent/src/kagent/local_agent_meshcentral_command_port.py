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
#: Wire envelope for one output body: the same 6 MB the Claw request route
#: already accepts for one user message. Above it the child is killed and the
#: outcome reports ``output_too_large`` — nothing is truncated and nothing is
#: buffered past this bound.
MAX_COMMAND_BYTES = 6_000_000
#: The same bound seen through the Base64 envelope, which is about four thirds
#: the size of what it carries. The child is killed on this number; the product
#: limit is still applied to the decoded PC bytes in ``parse_transcript``.
MAX_TRANSCRIPT_BYTES = MAX_COMMAND_BYTES * 4 // 3 + 4096


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


def _wrap(command: str, dispatch_id: str | None = None) -> str:
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
    dispatch's marker file - see ``cancel_kill_command``. Without one it is the
    same bytes as before, so nothing about a command's own result can change.
    """
    marks = ""
    clears = ""
    if dispatch_id is not None:
        marker = _pid_file_literal(dispatch_id)
        marks = (
            " $__padiem_pidfile=" + marker
            + "; Set-Content -LiteralPath $__padiem_pidfile -Value $PID -Encoding ascii;"
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
        ' Write-Output ("' + ENVELOPE_PREFIX + '" + '
        "[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes([string]$__padiem)));"
        ' Write-Output ("' + EXIT_SENTINEL + '" + $LASTEXITCODE)'
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
    if len(body) > MAX_COMMAND_BYTES:
        # The bound is the product's, on the PC's own bytes: the Base64 envelope
        # is bigger than its content, so the raw transcript is measured here.
        return "output_too_large", code, b""
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
        os.write(self._master, write_bytes)

    def wait_closed(self, seconds: float) -> None:
        import select

        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if select.select([self._master], [], [], 0.2)[0]:
                try:
                    if os.read(self._master, 65536) == b"":
                        break
                except OSError:
                    break
        self.close()

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
    ) -> None:
        if not callable(command_runner):
            raise ContractError("meshcentral command requires an injected command runner")
        # #4139: the streaming path is what actually bounds memory. The child is
        # read in chunks and killed the moment the transcript passes the wire
        # envelope, so a runaway command can never be buffered whole first.
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

    def run_command(
        self,
        *,
        node_ref: str,
        command: str,
        timeout_seconds: int | None = None,
        phase_observer: Callable[[str], None] | None = None,
        cancel_probe: Callable[[], bool] | None = None,
        dispatch_id: str | None = None,
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
        wrapped = _wrap(body, checked_dispatch)
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
        return self._run_streaming(
            argv, password, timeout_seconds, phase, cancelled,
            node_ref=node_ref.strip(), dispatch_id=checked_dispatch,
        )

    # ---- streaming execution -------------------------------------------
    def _run_streaming(
        self, argv: list[str], password: str, timeout_seconds: int | None,
        phase: Callable[[str], None],
        cancelled: Callable[[], bool] | None = None,
        *,
        node_ref: str | None = None,
        dispatch_id: str | None = None,
    ) -> MeshCentralCommandOutcome:
        """Read the child's transcript in bounded chunks.

        Memory is bounded by the wire envelope plus one chunk: the moment the
        transcript passes it, the child is killed and the outcome reports
        ``output_too_large``. A ``timeout_seconds`` of None means no PADIEM client
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
        total = 0
        oversize = False
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
                    )
                # None deadline: wait on the console with a fixed read slice so
                # the loop stays responsive to the child finishing.
                remaining = 1.0 if deadline is None else deadline - time.monotonic()
                if deadline is not None and remaining <= 0:
                    process.kill()
                    phase("timeout")
                    return MeshCentralCommandOutcome(
                        termination="timed_out", exit_code=None, output=b"",
                    )
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
                        )
                    continue
                chunks.append(chunk)
                total += len(chunk)
                if total > MAX_TRANSCRIPT_BYTES:
                    oversize = True
                    process.kill()
                    break
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
            raise MeshCentralCommandRefused("the official meshcentral client failed") from None
        raw = b"".join(chunks)
        if oversize:
            phase("reply")
            return MeshCentralCommandOutcome(
                termination="output_too_large", exit_code=None, output=b"",
            )
        outcome = self._from_transcript(raw)
        phase("reply")
        return outcome

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

    def kill_command_process(self, *, node_ref: str, dispatch_id: str) -> None:
        """End exactly one dispatch's own process tree on the PC.

        ``runcommand`` cannot carry a stop: it is the queue the running command is
        holding. ``meshctrl shell`` opens the agent's terminal over its own session,
        which is the channel that worked by hand on 2026-10-28 while the queue was
        wedged. The command sent through it names only the stopped dispatch's pid
        marker - no image name, no service, no window title - and the whole session
        is bounded, so an unreachable agent cannot make this the new way to hang.
        """
        import subprocess

        checked = _checked_dispatch_id(dispatch_id)
        if not isinstance(node_ref, str) or not node_ref.strip():
            raise MeshCentralCommandRefused("node_ref is required")
        if self._popen_factory is None:
            raise MeshCentralCommandRefused("stopping a command needs the streaming client")
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
            (password + "\n" + cancel_kill_command(checked) + "\n").encode("utf-8"),
        )
        child = self._popen_factory(
            argv, stdin=handoff.slave, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
        )
        handoff.wait_closed(CANCEL_KILL_WAIT_SECONDS)
        if child.poll() is None:
            child.kill()

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
    "MAX_COMMAND_BYTES",
    "MAX_TRANSCRIPT_BYTES",
    "MERGED_STREAMS",
    "METHOD_LABEL",
    "MeshCentralCliCommandPort",
    "MeshCentralCommandOutcome",
    "MeshCentralCommandRefused",
    "parse_transcript",
]
