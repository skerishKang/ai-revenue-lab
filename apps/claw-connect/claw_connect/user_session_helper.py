"""#7065 (c) stage 1 — the per-PC "logged-in user helper" protocol.

Why this exists
---------------
The Connector always runs as the MeshCentral agent, and on Windows that agent is
a service (``LocalSystem``). Measured 2026-11-07: every command on COM1 and COM2
reported ``nt authority\\system``. ``--runasuser`` exists in the official client
but is ignored on Windows (MeshCentral #4949, #6430, unresolved), so no amount of
tuning on that path reaches the logged-in user's session. WSL lives in that
session too, which is why ``wsl.exe -l -q`` answered exit -1 with no output.

The helper is a small program that runs *inside* the logged-in user's session and
executes one request at a time. The SYSTEM agent stops running commands itself
and forwards them over a local named pipe. Authority moves DOWN (SYSTEM →
interactive user), which is the safe direction.

Stage 1 scope
-------------
* ``whoami`` — the identity check that proves the helper is in the user session.
* One request = one process. No reuse, no pooling, no long-lived child.
* A logged-out user is reported as ``user_session_unavailable``. The SYSTEM agent
  never silently runs the command instead.

Stage 2 scope (#7105)
---------------------
The owner's decision (2026-11-07) is that an ordinary user request runs as the
logged-in Windows user, so the helper runs the Windows shells ``powershell``
(``powershell.exe -EncodedCommand``), ``cmd`` (``cmd.exe /c``) and — since
#7188 R4 ④ — ``bash`` (the located Git Bash, ``bash.exe -lc``). The wire
format, the nonce, the replay guard and the one-process rule are unchanged:
stage 2 adds shell values, not a second protocol.

There is no read-only allowlist any more. It guarded the removed ``wsl``
observation lane; the dispatch itself is the authorization and authority still
moves DOWN (SYSTEM → the logged-in user). The command text is still checked
before a process exists: bounded length, no NUL, no control characters.

The wsl shell is gone (#7188 R4 ④): the owner banned WSL on the PC, so bash
runs the Git Bash that :func:`locate_git_bash` finds — the same candidate
order (registry ``InstallPath``, PATH ``git.exe`` relatives, fixed standard
roots) the SYSTEM dispatcher uses — and reports ``user_helper_bash_missing``
when none exists. A ``distro`` field in a request is refused.

Not here: file writes through an editor, find/replace editing, interactive
stdin, and the switch that makes ``user`` the default mode (that is a separate
decision).

Wire format
-----------
Request (JSON, UTF-8)::

    {"request_id": "req_<32 hex>", "nonce": "<hex hmac>",
     "shell": "bash"|"powershell"|"cmd"|"whoami",
     "cwd": null|str, "command": str, "timeout_seconds": int, "distro": null|str}

``distro`` stays in the frame for wire compatibility but must be ``null``: the
``wsl`` shell it belonged to was removed (#7188 R4 ④, owner ban on WSL).

Reply (JSON, UTF-8)::

    {"request_id": ..., "status": "ok"|"error", "exit_code": int|null,
     "stdout_b64": str, "stderr_b64": str, "truncated": bool,
     "error_code": null|str, "duration_ms": int}

Bodies are Base64 of UTF-8 on both sides. A Korean console answers in cp949, and
the same frame rule that #5573 established for the MeshCentral lane applies here:
only ASCII crosses the pipe, so a codepage can never destroy an answer.

The pipe
--------
``\\\\.\\pipe\\padiem-user-helper-<device_id>``, ACL'd to SYSTEM plus that one
user. No network listener, nothing bound to a port, nothing reachable off-box.

The nonce is an HMAC over the request material keyed by the PC's deployment
secret (the ``executor.env`` family already on the machine), so the secret never
travels and a request cannot be replayed: each ``request_id`` is accepted once.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

# ---------------------------------------------------------------------------
# Error codes. Each one names a different fact, so an operator never has to
# guess whether the user was logged out, the helper was slow, or it said no.
# ---------------------------------------------------------------------------
USER_SESSION_UNAVAILABLE = "user_session_unavailable"
USER_HELPER_TIMEOUT = "user_helper_timeout"
USER_HELPER_REFUSED = "user_helper_refused"
USER_HELPER_BAD_REQUEST = "user_helper_bad_request"
USER_HELPER_BAD_REPLY = "user_helper_bad_reply"
USER_HELPER_NOT_READ_ONLY = "user_helper_not_read_only"
#: #7188 R4 ④ — user-mode bash found no Git Bash through the shared
#: candidate order (registry, PATH git.exe relatives, fixed standard
#: roots). The same fact the SYSTEM lane reports as shell_unavailable 127.
USER_HELPER_BASH_MISSING = "user_helper_bash_missing"

SHELL_WHOAMI = "whoami"
SHELL_BASH = "bash"
SHELL_POWERSHELL = "powershell"
SHELL_CMD = "cmd"
#: #7105 stage 2 — the shells that run as the logged-in user. bash joined
#: in #7188 R4 ④: it runs the located Git Bash, never WSL (the owner
#: banned WSL on the PC), and it takes the stage-2 gate, not a read-only
#: allowlist.
STAGE2_SHELLS = (SHELL_BASH, SHELL_POWERSHELL, SHELL_CMD)
SUPPORTED_SHELLS = (SHELL_WHOAMI,) + STAGE2_SHELLS

PIPE_PREFIX = "padiem-user-helper-"
DEFAULT_TIMEOUT_SECONDS = 30
MAX_TIMEOUT_SECONDS = 120
#: Legacy direct-pipe read window; the stage-2 frame path no longer cuts output.
MAX_STREAM_BYTES = 262_144
#: #7107: the tool schema already accepts 50,000-character commands; the helper
#: must not be the narrower copy that refuses them.
MAX_COMMAND_CHARS = 50_000
MAX_CWD_CHARS = 1_024
#: How many request ids the helper remembers for replay refusal. A request is a
#: single observation, so this only has to outlive a retry window.
REPLAY_WINDOW = 512

_REQUEST_ID = re.compile(r"req_[0-9a-f]{32}\Z")
#: Raw device identifiers from MeshCentral may contain alphanumerics and '$' (and '@', '.', '-', '_', ':', '+').
#: The pipe name is derived as a stable hash so arbitrary safe raw ids map to the
#: same pipe across helper/install/executor. Validate minimally (no whitespace/control/path separators).
_DEVICE_ID_RAW = re.compile(r"^[A-Za-z0-9_.$:@+\-]{1,256}\Z")
#: Anything that could start a second command, write a file or expand a


class UserHelperError(RuntimeError):
    """One bounded refusal. Carries a code, never output and never a secret."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


#: #7188 R4 ④ — where a Git for Windows install registers itself. One
#: source for both lanes: the SYSTEM dispatcher probes these same keys in
#: PowerShell and the helper reads them here through ``winreg``. The pairs
#: mirror ``padiem_ai_core.pc_shell_selection.GIT_BASH_REGISTRY_KEYS``; the
#: helper's single-file build must not import the Core table, so the
#: contract test pins the two copies equal.
GIT_BASH_REGISTRY_KEYS = (
    ("HKLM", "SOFTWARE\\GitForWindows"),
    ("HKLM", "SOFTWARE\\WOW6432Node\\GitForWindows"),
    ("HKCU", "SOFTWARE\\GitForWindows"),
)
#: Fixed standard-install roots, expanded on this PC. Mirrors
#: ``padiem_ai_core.pc_shell_selection.GIT_BASH_CANDIDATES``
#: (contract-pinned).
GIT_BASH_FIXED_CANDIDATES = (
    r"%ProgramW6432%\Git\bin\bash.exe",
    r"%ProgramFiles%\Git\bin\bash.exe",
    r"%ProgramFiles%\Git\usr\bin\bash.exe",
    r"%ProgramFiles(x86)%\Git\bin\bash.exe",
    r"%LocalAppData%\Programs\Git\bin\bash.exe",
)
#: bash locations probed relative to a ``git.exe`` found on PATH. Mirrors
#: ``padiem_ai_core.pc_shell_selection.GIT_BASH_PATH_RELATIVES``.
GIT_BASH_PATH_RELATIVES = (r"..\bin\bash.exe", r"..\..\bin\bash.exe")


def _winreg_install_path(hive: str, subkey: str) -> str | None:
    """``InstallPath`` from one Git for Windows registry key, or None.

    Non-Windows hosts and missing keys are the same "not here" answer; a
    present-but-empty value is not a location.
    """
    try:
        import winreg
    except ImportError:
        return None
    hive_const = {"HKLM": winreg.HKEY_LOCAL_MACHINE,
                  "HKCU": winreg.HKEY_CURRENT_USER}.get(hive)
    if hive_const is None:
        return None
    try:
        with winreg.OpenKey(hive_const, subkey) as key:
            value, _ = winreg.QueryValueEx(key, "InstallPath")
    except OSError:
        return None
    if isinstance(value, str) and value.strip():
        return value
    return None


def _is_real_git_bash(candidate: str, isfile) -> bool:
    """One candidate path names an existing bash.exe that is not WSL's.

    ``C:\\Windows\\System32\\bash.exe`` is the WSL bash every Windows
    machine ships; picking it is exactly the #7266 defect. The guard runs on
    every probe stage, so a manipulated registry value or a planted PATH
    entry cannot smuggle it in either.
    """
    if not isfile(candidate):
        return False
    lowered = candidate.lower()
    if "\\windows\\system32\\" in lowered:
        return False
    if lowered.endswith("\\wsl.exe"):
        return False
    return True


def locate_git_bash(*, open_key=None, which=None, expandvars=None, isfile=None) -> str | None:
    """The Git Bash this PC runs for bash requests, or None.

    One candidate order for both lanes (#7188 R4 ④), probed in this order:

    1. registry ``InstallPath`` — HKLM, HKLM\\WOW6432Node, HKCU
       ``SOFTWARE\\GitForWindows``; the file is ``<InstallPath>\bin\bash.exe``.
    2. ``git.exe`` on PATH — ``<git dir>\..\bin\bash.exe`` and
       ``<git dir>\..\..\bin\bash.exe`` cover the ``cmd\`` and
       ``mingw64\bin\`` PATH layouts.
    3. the fixed standard roots (``%ProgramW6432%`` first for the 32-bit
       PowerShell redirect, then ``%ProgramFiles%``, ``%ProgramFiles(x86)%``,
       ``%LocalAppData%``).

    There is deliberately no ``bash.exe`` PATH fallback and no WSL step: the
    owner banned WSL on the PC, and a bare PATH hunt is what picked
    ``System32\bash.exe`` on COM1 (#7266). Every stage passes
    :func:`_is_real_git_bash`, so the WSL bash is never returned even when a
    registry value or PATH entry points at it.

    The probes are parameters so tests can isolate the host's registry, PATH
    and environment; production uses the defaults.
    """
    open_key = open_key or _winreg_install_path
    which = which or (lambda name: __import__("shutil").which(name))
    expandvars = expandvars or (lambda value: os.path.expandvars(value))
    isfile = isfile or os.path.isfile

    for hive, subkey in GIT_BASH_REGISTRY_KEYS:
        install_path = open_key(hive, subkey)
        if install_path:
            candidate = os.path.normpath(os.path.join(install_path, "bin", "bash.exe"))
            if _is_real_git_bash(candidate, isfile):
                return candidate
    git = which("git.exe")
    if git:
        git_dir = os.path.dirname(os.path.abspath(git))
        # A git.exe under System32 is WSL's or a planted one; its siblings
        # are Windows system directories, never a Git for Windows install.
        if "\\windows\\system32" not in git_dir.lower():
            for relative in GIT_BASH_PATH_RELATIVES:
                candidate = os.path.normpath(os.path.join(git_dir, relative))
                if _is_real_git_bash(candidate, isfile):
                    return candidate
    for template in GIT_BASH_FIXED_CANDIDATES:
        candidate = os.path.normpath(expandvars(template))
        if _is_real_git_bash(candidate, isfile):
            return candidate
    return None


def device_id_pipe_suffix(device_id: str) -> str:
    """Derive the pipe identifier suffix from a raw device id.

    Use sha256 of the raw UTF-8 device id hex-prefix to produce a stable
    ``dev_<32hex>`` suffix regardless of original charset (e.g. '$').
    """
    if not isinstance(device_id, str) or _DEVICE_ID_RAW.fullmatch(device_id) is None:
        raise UserHelperError(USER_HELPER_BAD_REQUEST, "device_id is not a device identifier")
    h = hashlib.sha256(device_id.encode("utf-8")).hexdigest()
    return "dev_" + h[:32]


def pipe_name(device_id: str) -> str:
    """The local pipe this PC's helper listens on.

    Accepts raw device identifiers from MeshCentral (may include '$' etc.)
    and derives a stable hashed pipe name. The returned name is always of
    form ``padiem-user-helper-dev_<32hex>``.
    """
    return PIPE_PREFIX + device_id_pipe_suffix(device_id)


def pipe_path(device_id: str) -> str:
    """The Windows path form of :func:`pipe_name`."""
    return "\\\\.\\pipe\\" + pipe_name(device_id)


@dataclass(frozen=True, slots=True)
class HelperRequest:
    """One validated request. Constructed only through :func:`parse_request`."""

    request_id: str
    nonce: str
    shell: str
    command: str
    timeout_seconds: int
    cwd: str | None = None
    distro: str | None = None

    def material(self) -> bytes:
        """The exact bytes the nonce signs.

        Field order and separators are fixed here so the helper and the agent
        cannot drift: a change to this method is a protocol change, and both
        sides sign the same string or the request is refused.
        """
        parts = (
            self.request_id,
            self.shell,
            self.cwd or "",
            self.command,
            str(self.timeout_seconds),
            self.distro or "",
        )
        return "\n".join(parts).encode("utf-8")


def request_nonce(secret: bytes, request: HelperRequest) -> str:
    """The HMAC the agent attaches and the helper recomputes."""
    if not isinstance(secret, (bytes, bytearray)) or not secret:
        raise UserHelperError(USER_HELPER_BAD_REQUEST, "the deployment secret is empty")
    return hmac.new(bytes(secret), request.material(), hashlib.sha256).hexdigest()


def verify_nonce(secret: bytes, request: HelperRequest) -> bool:
    """Constant-time check of the request's own nonce."""
    if not isinstance(request.nonce, str) or not request.nonce:
        return False
    try:
        expected = request_nonce(secret, request)
    except UserHelperError:
        return False
    return hmac.compare_digest(expected, request.nonce)


def _bounded_text(value: Any, limit: int) -> str | None:
    if not isinstance(value, str) or not value or len(value) > limit:
        return None
    if any(ord(char) < 32 for char in value):
        return None
    return value


def is_windows_shell_command(command: str) -> bool:
    """Whether one stage-2 command is a runnable Windows command line.

    This is the stage-1 style gate applied to a shell that is allowed to do real
    work: the command must be one bounded string with no NUL and no control
    characters (tab, newline and carriage return belong in a real script). No
    verb allowlist is applied here — the approved dispatch is what authorizes the
    command, and the account the process runs as is strictly less privileged
    than the SYSTEM agent that forwarded it.
    """
    if not isinstance(command, str):
        return False
    if not command.strip() or len(command) > MAX_COMMAND_CHARS:
        return False
    for char in command:
        if ord(char) < 32 and char not in ("\t", "\n", "\r"):
            return False
    return True


def parse_request(payload: Mapping[str, Any]) -> HelperRequest:
    """Validate one request frame, or refuse it with the reason.

    Refusal is total: a frame with an unknown key, a missing field or a shell
    this stage does not run produces no process at all.
    """
    if not isinstance(payload, Mapping):
        raise UserHelperError(USER_HELPER_BAD_REQUEST, "request must be an object")
    allowed = {"request_id", "nonce", "shell", "cwd", "command", "timeout_seconds", "distro"}
    if set(payload) - allowed:
        raise UserHelperError(USER_HELPER_BAD_REQUEST, "request carries an unknown field")

    request_id = payload.get("request_id")
    if not isinstance(request_id, str) or _REQUEST_ID.fullmatch(request_id) is None:
        raise UserHelperError(USER_HELPER_BAD_REQUEST, "request_id is not a request identifier")
    nonce = payload.get("nonce")
    # The nonce is an authentication fact, not a schema fact: the agent builds a
    # request and then signs it, so an unsigned request is well-formed and simply
    # fails verification. A non-string nonce is still a malformed frame.
    if not isinstance(nonce, str) or len(nonce) > 128:
        raise UserHelperError(USER_HELPER_BAD_REQUEST, "nonce is not text")

    shell = payload.get("shell", SHELL_WHOAMI)
    if shell not in SUPPORTED_SHELLS:
        raise UserHelperError(USER_HELPER_REFUSED, "shell is not one this helper runs")

    command = payload.get("command")
    if not isinstance(command, str) or not command or len(command) > MAX_COMMAND_CHARS:
        raise UserHelperError(USER_HELPER_BAD_REQUEST, "command is missing or too long")

    timeout = payload.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 0:
        # #7107: kept as signed request material for wire compatibility, but it
        # is not an execution deadline. The command runs until it ends.
        raise UserHelperError(USER_HELPER_BAD_REQUEST, "timeout_seconds must be a non-negative integer")

    cwd = payload.get("cwd")
    if cwd is not None and _bounded_text(cwd, MAX_CWD_CHARS) is None:
        raise UserHelperError(USER_HELPER_BAD_REQUEST, "cwd is not a usable path")

    distro = payload.get("distro")
    # The field stays in the wire contract (the executor's pipe client always
    # sends it, possibly ``null``) but no shell consumes it any more: the wsl
    # shell was removed with the owner's WSL ban.
    if distro is not None:
        raise UserHelperError(USER_HELPER_BAD_REQUEST, "distro belongs to the removed wsl shell")

    if shell == SHELL_WHOAMI:
        # The identity probe is one exact command. It is not a general shell.
        if command.strip() != "whoami":
            raise UserHelperError(USER_HELPER_REFUSED, "the whoami shell runs whoami only")
    elif not is_windows_shell_command(command):
        raise UserHelperError(USER_HELPER_BAD_REQUEST,
                              "command is not a runnable Windows command line")

    return HelperRequest(
        request_id=request_id,
        nonce=nonce,
        shell=shell,
        command=command,
        timeout_seconds=timeout,
        cwd=cwd,
        distro=distro,
    )


# ---------------------------------------------------------------------------
# Execution: one request, one process, no reuse.
# ---------------------------------------------------------------------------
#: The trailer that makes a stage-2 PowerShell request report the exit code of
#: the last native command it ran, the same rule the SYSTEM lane applies. A
#: command that ends in its own ``exit`` never reaches it, which is correct.
_POWERSHELL_EXIT_TAIL = (
    "\n$__padiem_exit=0\n"
    "if($null -ne $LASTEXITCODE){$__padiem_exit=[int]$LASTEXITCODE}\n"
    "exit $__padiem_exit\n"
)


def powershell_envelope(command: str) -> str:
    """The script handed to ``powershell.exe -EncodedCommand`` for one request.

    The command is the script: it is not spliced into a shell word list, so a
    quote in it cannot become a second command. The console is pinned to UTF-8
    for the same reason #7068 pinned the SYSTEM lane: a Korean-locale console
    otherwise returns bytes in its own code page.
    """
    return (
        "$ErrorActionPreference='Continue'\n"
        "$ProgressPreference='SilentlyContinue'\n"
        "try{[Console]::OutputEncoding=[Text.Encoding]::UTF8}catch{}\n"
        + command
        + _POWERSHELL_EXIT_TAIL
    )


def build_argv(request: HelperRequest) -> list[str]:
    """The argv for exactly one process, built from validated parts only.

    The command travels as its own argv element, never as a shell string, so a
    quote or a space in it cannot become a second command. bash runs the Git
    Bash :func:`locate_git_bash` found — never ``wsl.exe`` and never
    ``System32\\bash.exe``. PowerShell receives the
    script Base64-encoded (UTF-16LE), the same shape the SYSTEM lane uses, so no
    quoting rule of any caller can rewrite it.
    """
    if request.shell == SHELL_WHOAMI:
        return ["whoami.exe"]
    if request.shell == SHELL_POWERSHELL:
        encoded = base64.b64encode(
            powershell_envelope(request.command).encode("utf-16-le")
        ).decode("ascii")
        return [
            "powershell.exe", "-NoProfile", "-NonInteractive",
            "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded,
        ]
    if request.shell == SHELL_CMD:
        return ["cmd.exe", "/d", "/s", "/c", request.command]
    if request.shell != SHELL_BASH:
        raise UserHelperError(USER_HELPER_REFUSED, "shell is not one this helper runs")
    if not is_windows_shell_command(request.command):
        raise UserHelperError(USER_HELPER_BAD_REQUEST,
                              "command is not a runnable Windows command line")
    bash = locate_git_bash()
    if bash is None:
        raise UserHelperError(USER_HELPER_BASH_MISSING,
                              "no Git Bash through registry, PATH git.exe or standard roots")
    return [bash, "-lc", request.command]


@dataclass(frozen=True, slots=True)
class HelperReply:
    """What one request actually produced, exactly as observed."""

    request_id: str
    status: str
    exit_code: int | None
    stdout: bytes = b""
    stderr: bytes = b""
    truncated: bool = False
    error_code: str | None = None
    duration_ms: int = 0

    def to_frame(self) -> dict[str, Any]:
        """The JSON object that crosses the pipe. Bodies are Base64 of UTF-8."""
        return {
            "request_id": self.request_id,
            "status": self.status,
            "exit_code": self.exit_code,
            "stdout_b64": base64.b64encode(self.stdout).decode("ascii"),
            "stderr_b64": base64.b64encode(self.stderr).decode("ascii"),
            "truncated": self.truncated,
            "error_code": self.error_code,
            "duration_ms": self.duration_ms,
        }


def error_reply(request_id: str, code: str, *, detail: str = "",
                duration_ms: int = 0) -> HelperReply:
    """A refusal that still says which request it answers and why.

    ``detail`` is this module's own short sentence. It is never command output,
    so a refusal cannot leak what the command would have printed.
    """
    return HelperReply(
        request_id=request_id,
        status="error",
        exit_code=None,
        stderr=detail.encode("utf-8") if detail else b"",
        error_code=code,
        duration_ms=duration_ms,
    )


#: Signature of the runner seam. Tests pass a double; production passes
#: :func:`run_process`. Keeping it a parameter is what lets the suite prove the
#: one-process rule without starting a real WSL distribution.
Runner = Callable[[Sequence[str], str | None, int | None], tuple[int | None, bytes, bytes]]


def run_process(argv: Sequence[str], cwd: str | None, timeout_seconds: int | None
                ) -> tuple[int | None, bytes, bytes]:
    """Start one process, wait for it, and return what it printed.

    #7107: there is deliberately no timeout. The owner's stop is what ends a
    command; a fixed 30/120-second deadline turned every long-but-healthy job
    into a failure. The exit code is the child's own; it is never inferred from
    "the process started".
    """
    try:
        completed = subprocess.run(  # noqa: S603 - argv is built from validated parts
            list(argv),
            cwd=cwd,
            capture_output=True,
            timeout=None,
            check=False,
        )
    except FileNotFoundError as missing:
        raise UserHelperError(USER_HELPER_REFUSED, "the executable is not on this PC") from missing
    return completed.returncode, completed.stdout or b"", completed.stderr or b""


def serve_one(request: HelperRequest, *, secret: bytes, runner: Runner = run_process
              ) -> HelperReply:
    """Answer exactly one request with exactly one process.

    Order matters and is the security of this lane: the nonce is checked before
    anything is started, the read-only rule is checked again at argv build time,
    and only then does one process exist. A refused request starts nothing.
    """
    started = time.monotonic()
    if not verify_nonce(secret, request):
        return error_reply(request.request_id, USER_HELPER_REFUSED,
                           detail="the request nonce did not verify")
    try:
        argv = build_argv(request)
        exit_code, stdout, stderr = runner(argv, request.cwd, None)
    except UserHelperError as refused:
        return error_reply(request.request_id, refused.code, detail=refused.detail,
                           duration_ms=int((time.monotonic() - started) * 1000))
    # #7107: no per-stream cut. The caller pages the full body; a silent cut is
    # the one thing this lane must not present as the whole answer.
    return HelperReply(
        request_id=request.request_id,
        status="ok",
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        truncated=False,
        duration_ms=int((time.monotonic() - started) * 1000),
    )


# ---------------------------------------------------------------------------
# Replay guard. A request id is accepted once, and the window is bounded so a
# long-lived helper cannot grow without end.
# ---------------------------------------------------------------------------
@dataclass
class ReplayGuard:
    """Refuses a second sight of the same request id."""

    window: int = REPLAY_WINDOW
    seen: list[str] = field(default_factory=list)

    def accept(self, request_id: str) -> bool:
        if request_id in self.seen:
            return False
        self.seen.append(request_id)
        if len(self.seen) > self.window:
            del self.seen[: len(self.seen) - self.window]
        return True


# ---------------------------------------------------------------------------
# Frame decoding, used by the SYSTEM agent when the reply comes back.
# ---------------------------------------------------------------------------
def decode_reply(raw: bytes) -> HelperReply:
    """Read one reply frame, or refuse it.

    A body that is not valid UTF-8 is refused rather than shown: a mangled
    answer must never be presented as what the PC printed.
    """
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as bad:
        raise UserHelperError(USER_HELPER_BAD_REPLY, "the reply is not readable JSON") from bad
    if not isinstance(payload, Mapping):
        raise UserHelperError(USER_HELPER_BAD_REPLY, "the reply is not an object")
    request_id = payload.get("request_id")
    if not isinstance(request_id, str) or _REQUEST_ID.fullmatch(request_id) is None:
        raise UserHelperError(USER_HELPER_BAD_REPLY, "the reply has no request identifier")
    status = payload.get("status")
    if status not in ("ok", "error"):
        raise UserHelperError(USER_HELPER_BAD_REPLY, "the reply has no usable status")
    exit_code = payload.get("exit_code")
    if exit_code is not None and (not isinstance(exit_code, int) or isinstance(exit_code, bool)):
        raise UserHelperError(USER_HELPER_BAD_REPLY, "the reply exit code is not an integer")

    def _body(key: str) -> bytes:
        token = payload.get(key, "")
        if not isinstance(token, str):
            raise UserHelperError(USER_HELPER_BAD_REPLY, f"{key} is not text")
        try:
            data = base64.b64decode(token, validate=True) if token else b""
        except Exception as bad:
            raise UserHelperError(USER_HELPER_BAD_REPLY, f"{key} is not Base64") from bad
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as bad:
            raise UserHelperError(USER_HELPER_BAD_REPLY, f"{key} is not UTF-8") from bad
        return data

    error_code = payload.get("error_code")
    if error_code is not None and not isinstance(error_code, str):
        raise UserHelperError(USER_HELPER_BAD_REPLY, "error_code is not text")
    duration = payload.get("duration_ms", 0)
    if not isinstance(duration, int) or isinstance(duration, bool):
        duration = 0
    return HelperReply(
        request_id=request_id,
        status=status,
        exit_code=exit_code,
        stdout=_body("stdout_b64"),
        stderr=_body("stderr_b64"),
        truncated=bool(payload.get("truncated", False)),
        error_code=error_code,
        duration_ms=duration,
    )


# ---------------------------------------------------------------------------
# The SYSTEM agent's side: forward, or report that the user is not there.
# ---------------------------------------------------------------------------
def forward_to_helper(request: HelperRequest, *, secret: bytes, device_id: str,
                      connect: Callable[[str], Any] | None = None) -> HelperReply:
    """Hand one request to the logged-in user's helper over the local pipe.

    When the helper is absent the user is logged out, and that is reported as
    ``user_session_unavailable``. The SYSTEM agent does not run the command
    itself: silently answering as SYSTEM is the exact behaviour #7065 exists to
    remove, and it would make a logged-out PC look healthy.
    """
    path = pipe_path(device_id)
    opener = connect or _open_pipe
    try:
        handle = opener(path)
    except FileNotFoundError as absent:
        raise UserHelperError(USER_SESSION_UNAVAILABLE,
                              "no helper is listening; the user is not logged in") from absent
    except OSError as unavailable:
        raise UserHelperError(USER_SESSION_UNAVAILABLE,
                              "the helper pipe could not be opened") from unavailable
    try:
        frame = json.dumps({
            "request_id": request.request_id,
            "nonce": request_nonce(secret, request),
            "shell": request.shell,
            "cwd": request.cwd,
            "command": request.command,
            "timeout_seconds": request.timeout_seconds,
            "distro": request.distro,
        }, ensure_ascii=True).encode("utf-8")
        raw = _exchange(handle, frame, timeout_seconds=request.timeout_seconds + 5)
    finally:
        _close(handle)
    return decode_reply(raw)


def _open_pipe(path: str) -> Any:
    """Open the helper's pipe. Windows only, and only that one pipe name."""
    import sys  # noqa: PLC0415 - platform gate, not a module-level dependency

    if sys.platform != "win32":
        raise FileNotFoundError(path)
    return open(path, "r+b", buffering=0)  # noqa: SIM115 - closed by the caller


def _exchange(handle: Any, frame: bytes, *, timeout_seconds: int) -> bytes:
    """One write, one read, bounded. A pipe that stalls is a timeout, not a hang."""
    handle.write(frame)
    if hasattr(handle, "flush"):
        handle.flush()
    return handle.read(MAX_STREAM_BYTES * 2)


def _close(handle: Any) -> None:
    try:
        handle.close()
    except Exception:
        pass

