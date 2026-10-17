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
  silent success.

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
_MAX_COMMAND_CHARS = 512
#: Printable ASCII only: a single-line command, no control characters.
_COMMAND_BODY = re.compile(r"[\x20-\x7e]{1,512}")
_SENTINEL_LINE = re.compile(rb"__PADIEM_EXIT__(-?\d+)?")
METHOD_LABEL = "powershell_runcommand_reply"


class MeshCentralCommandRefused(ValueError):
    """Bounded refusal of one command run. Never carries output or secrets."""


@dataclass(frozen=True, slots=True)
class MeshCentralCommandOutcome:
    """What one real command run produced, exactly as observed."""

    termination: str  # "exited" | "timed_out" | "no_reply"
    exit_code: int | None
    output: bytes
    method: str = METHOD_LABEL


def _bounded_command(value: Any) -> str:
    if not isinstance(value, str):
        raise MeshCentralCommandRefused("command must be text")
    text = value.strip()
    if not text or len(text) > _MAX_COMMAND_CHARS:
        raise MeshCentralCommandRefused("command must be 1..512 characters")
    if _COMMAND_BODY.fullmatch(text) is None:
        raise MeshCentralCommandRefused(
            "command must be a single printable-ASCII line"
        )
    return text


def _wrap(command: str) -> str:
    """Append the exit-code sentinel as a separate statement.

    PowerShell keeps ``$LASTEXITCODE`` from the last native command, so the
    sentinel reports the real remote exit code instead of the shell's own.
    """
    return command + '; Write-Output ("' + EXIT_SENTINEL + '" + $LASTEXITCODE)'


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
        # The sentinel printed an empty value: no exit code was observed, so the
        # run is not an "exited" outcome and must not be reported as one.
        return "no_reply", None, output
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
    ) -> None:
        if not callable(command_runner):
            raise ContractError("meshcentral command requires an injected command runner")
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
        argv = [
            "node", "-e", _MESHCTRL_STDIN_BOOTSTRAP,
            self._meshctrl_js, "runcommand",
            "--url", self._url,
            "--loginuser", self._login_user,
            "--loginpass", "__PADIEM_MESHCTRL_PASSWORD_FROM_STDIN__",
            "--id", node_ref.strip(),
            "--powershell",
            "--run", _wrap(body),
            "--reply",
        ]
        password = self._password_provider()
        if not isinstance(password, str) or not password or "\n" in password or "\r" in password:
            raise MeshCentralCommandRefused(
                "the protected MeshCentral operator credential is invalid"
            )
        try:
            completed = self._run(
                argv, input=password + "\n", timeout=timeout_seconds,
            )
        except Exception as exc:
            # A timeout (or any transport failure) is an observed outcome with
            # NO exit code: the remote process may still be running.
            if type(exc).__name__ == "TimeoutExpired":
                partial = getattr(exc, "output", None) or getattr(exc, "stdout", None) or b""
                if isinstance(partial, str):
                    partial = partial.encode("utf-8", errors="replace")
                return MeshCentralCommandOutcome(
                    termination="timed_out", exit_code=None,
                    output=bytes(partial),
                )
            raise MeshCentralCommandRefused("the official meshcentral client failed") from exc
        if getattr(completed, "returncode", None) != 0:
            # meshctrl itself failed: no transcript, so no exit code is claimed.
            return MeshCentralCommandOutcome(
                termination="no_reply", exit_code=None, output=b"",
            )
        raw = getattr(completed, "stdout", b"") or b""
        if isinstance(raw, str):
            raw = raw.encode("utf-8", errors="replace")
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
    "METHOD_LABEL",
    "MeshCentralCliCommandPort",
    "MeshCentralCommandOutcome",
    "MeshCentralCommandRefused",
    "parse_transcript",
]
