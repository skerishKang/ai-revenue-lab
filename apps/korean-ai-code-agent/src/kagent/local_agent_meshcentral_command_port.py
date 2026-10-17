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
leading/trailing whitespace, minus the sentinel line this module itself added.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from .contracts import ContractError
from .local_agent_meshcentral_private_reader import _MESHCTRL_STDIN_BOOTSTRAP

#: Marker appended to the requested command so the PC reports its own exit code.
EXIT_SENTINEL = "__PADIEM_EXIT__"
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
#: stdout and stderr travel merged (trailing ``2>&1``); the conversation says so.
MERGED_STREAMS = True
#: Wire envelope for one output body: the same 6 MB the Claw request route
#: already accepts for one user message. Above it the child is killed and the
#: outcome reports ``output_too_large`` — nothing is truncated and nothing is
#: buffered past this bound.
MAX_COMMAND_BYTES = 6_000_000


class MeshCentralCommandRefused(ValueError):
    """Bounded refusal of one command run. Never carries output or secrets."""


@dataclass(frozen=True, slots=True)
class MeshCentralCommandOutcome:
    """What one real command run produced, exactly as observed."""

    #: "exited" | "timed_out" | "no_reply" | "no_exit_code" | "output_too_large"
    #: no_reply means the console never answered; no_exit_code means it answered
    #: completely and PowerShell had no code to report.
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


def _wrap(command: str) -> str:
    """Merge the error stream, then append the exit-code sentinel.

    Measured on the real PC: without the merge, a command that writes to stderr
    either loses that text or never returns a transcript at all; with a trailing
    ``2>&1`` the same command returns its error text through the console. The
    merge is applied to the *whole* trailing statement only — a multi-statement
    command keeps its own stream wiring for the earlier statements, and the
    conversation states that the streams are merged.

    ``$LASTEXITCODE`` is PowerShell's record of the last native command, so the
    sentinel reports the real remote exit code instead of the shell's own.
    """
    return (
        command + " 2>&1; Write-Output (\""
        + EXIT_SENTINEL + "\" + $LASTEXITCODE)"
    )


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
    if raw_code is None:
        # The sentinel printed an empty value. That is not a console that never
        # answered: PowerShell records `$LASTEXITCODE` only for "the exit code of
        # the last native program or PowerShell script that ran" (Microsoft,
        # about_Automatic_Variables), so a pipeline made only of cmdlets and .NET
        # calls leaves it empty while still returning its whole output. The code
        # stays unobserved here and is never turned into 0.
        return "no_exit_code", None, output
    return "exited", int(raw_code), output


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
    ) -> None:
        if not callable(command_runner):
            raise ContractError("meshcentral command requires an injected command runner")
        # #4139: the streaming path is what actually bounds memory. The child is
        # read in chunks and killed the moment the transcript passes the wire
        # envelope, so a runaway command can never be buffered whole first.
        self._popen_factory = popen_factory
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
        self, *, node_ref: str, command: str, timeout_seconds: int = 60
    ) -> MeshCentralCommandOutcome:
        if not isinstance(node_ref, str) or not node_ref.strip():
            raise MeshCentralCommandRefused("node_ref is required")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int):
            raise MeshCentralCommandRefused("timeout_seconds must be an integer")
        if timeout_seconds < 1 or timeout_seconds > 300:
            raise MeshCentralCommandRefused("timeout_seconds is out of range")
        body = _bounded_command(command)
        wrapped = _wrap(body)
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
            try:
                completed = self._run(
                    argv, input=password + "\n", timeout=timeout_seconds,
                )
            except Exception as exc:
                if type(exc).__name__ == "TimeoutExpired":
                    return MeshCentralCommandOutcome(
                        termination="timed_out", exit_code=None, output=b"",
                    )
                raise MeshCentralCommandRefused(
                    "the official meshcentral client failed"
                ) from exc
            if getattr(completed, "returncode", None) != 0:
                return MeshCentralCommandOutcome(
                    termination="no_reply", exit_code=None, output=b"",
                )
            raw = getattr(completed, "stdout", b"") or b""
            if isinstance(raw, str):
                raw = raw.encode("utf-8", errors="replace")
            return self._from_transcript(raw)
        return self._run_streaming(argv, password, timeout_seconds)

    # ---- streaming execution -------------------------------------------
    def _run_streaming(
        self, argv: list[str], password: str, timeout_seconds: int
    ) -> MeshCentralCommandOutcome:
        """Read the child's transcript in bounded chunks.

        Memory is bounded by the wire envelope plus one chunk: the moment the
        transcript passes it, the child is killed and the outcome reports
        ``output_too_large``. A command that never answers is killed at the
        deadline and reported as ``timed_out`` — the remote process may still be
        running, so no exit code is claimed.
        """
        import subprocess
        import time

        process = self._popen_factory(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        chunks: list[bytes] = []
        total = 0
        oversize = False
        try:
            if process.stdin is not None:
                process.stdin.write((password + "\n").encode("utf-8"))
                process.stdin.flush()
                process.stdin.close()
            deadline = time.monotonic() + timeout_seconds
            while True:
                if time.monotonic() > deadline:
                    process.kill()
                    return MeshCentralCommandOutcome(
                        termination="timed_out", exit_code=None, output=b"",
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    process.kill()
                    return MeshCentralCommandOutcome(
                        termination="timed_out", exit_code=None, output=b"",
                    )
                chunk = _read_some(process, max(0.05, min(1.0, remaining)))
                if not chunk:
                    if process.poll() is not None:
                        break
                    continue
                chunks.append(chunk)
                total += len(chunk)
                if total > MAX_COMMAND_BYTES:
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
            return MeshCentralCommandOutcome(
                termination="output_too_large", exit_code=None, output=b"",
            )
        return self._from_transcript(raw)

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
    "EXIT_SENTINEL",
    "MAX_COMMAND_BYTES",
    "MERGED_STREAMS",
    "METHOD_LABEL",
    "MeshCentralCliCommandPort",
    "MeshCentralCommandOutcome",
    "MeshCentralCommandRefused",
    "parse_transcript",
]
