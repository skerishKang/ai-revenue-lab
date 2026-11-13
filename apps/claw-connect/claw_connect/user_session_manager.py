"""#7065 stage 3 — interactive sessions the user helper keeps between requests.

Why this exists
---------------
A stage-2 request is one process that lives exactly as long as the SYSTEM
client's pipe connection. That shape cannot carry a program that asks a
question: the output only travels when the process ends, the client's own wait
is bounded, and the PC's agent serves one command at a time, so nothing can
reach the program's input while it runs.

A session turns that around. The helper owns the program and keeps it between
requests; every operation — start, input, read, stop, status — is a short
request that returns at once. The connection is no longer the program's
lifetime, so a restart of the server side leaves the session where it was.

What this module is
-------------------
Pure session logic over two process backends: anonymous pipes (everywhere)
and a Windows pseudo console (:mod:`claw_connect.conpty_backend`, Windows 10
1809 and later). It knows nothing about the named pipe, the nonce or the frame:
the helper service authenticates a request first and then hands the operation
document here.

The wire contract (operation document, reply header, error codes) is the one
recorded on #7065 as "대화형 세션 연결 규약 v1". A reply is a header line (one
JSON object) followed by the output text, and it rides in the existing final
frame's ``stdout_b64``.

Rules that do not bend
----------------------
* A session never outlives the helper: every child is put in a kill-on-close
  job on Windows and ended on :meth:`SessionManager.shutdown`.
* Nobody watching is the only clock that ends a session. The program's own
  running time is never limited; a session with no request for ``keep_minutes``
  is ended and reported as ``expired``.
* Output is kept in memory only, bounded per session, and addressed by an
  absolute byte offset of its UTF-8 form. A read never cuts a character.
* Input is never retried and never logged here.
"""
from __future__ import annotations

import base64
import codecs
import ctypes
import json
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from .session_secret_output import SecretOutputFilter, prompt_hints
from .user_session_helper import (
    SHELL_BASH,
    SHELL_CMD,
    SHELL_POWERSHELL,
    SHELL_SESSION,
    USER_HELPER_BASH_MISSING,
    UserHelperError,
    default_working_directory,
    is_windows_shell_command,
    locate_git_bash,
    powershell_envelope,
    system_executable,
    windows_powershell_executable,
)

# ---------------------------------------------------------------------------
# Contract constants (#7065 "대화형 세션 연결 규약 v1").
# ---------------------------------------------------------------------------
SESSION_PROTOCOL_VERSION = 1
#: The value of the frame's ``shell`` field that marks a session request.
SESSION_SHELL = SHELL_SESSION

OP_START = "start"
OP_INPUT = "input"
OP_READ = "read"
OP_STOP = "stop"
OP_STATUS = "status"

PC_SESSION_NOT_FOUND = "pc_session_not_found"
PC_SESSION_ENDED = "pc_session_ended"
PC_SESSION_EXPIRED = "pc_session_expired"
PC_SESSION_LIMIT = "pc_session_limit"
PC_SESSION_START_FAILED = "pc_session_start_failed"
PC_SESSION_BAD_REQUEST = "pc_session_bad_request"
PC_SESSION_INPUT_TIMEOUT = "pc_session_input_timeout"
PC_SESSION_KEY_UNSUPPORTED = "pc_session_key_unsupported"

ENDED_EXITED = "exited"
ENDED_STOPPED = "stopped"
ENDED_EXPIRED = "expired"

BACKEND_PIPE = "pipe"
BACKEND_CONPTY = "conpty"

SESSION_SHELLS = (SHELL_POWERSHELL, SHELL_CMD, SHELL_BASH)
SESSION_KEYS = ("enter", "ctrl_c", "ctrl_d", "ctrl_z", "tab", "esc", "up", "down")
INPUT_ENCODINGS = ("utf-8", "cp949")

MAX_SESSIONS = 4
#: Ended sessions stay readable for a while; this bounds how many are kept.
MAX_ENDED_SESSIONS = 8
BUFFER_BYTES = 8 * 1024 * 1024
MAX_INPUT_CHARS = 4_000
MAX_COMMAND_CHARS = 50_000
READ_DEFAULT_BYTES = 32_768
READ_MAX_BYTES = 65_536
WAIT_DEFAULT_MS = 1_500
WAIT_MAX_MS = 10_000
#: Output is "settled" when nothing new arrived for this long.
SETTLE_MS = 300
KEEP_DEFAULT_MINUTES = 60
KEEP_MAX_MINUTES = 480
#: How long an ended session's output and exit code stay readable.
ENDED_KEEP_SECONDS = 30 * 60
#: A write that cannot enter the program's input within this is reported.
INPUT_WRITE_TIMEOUT_SECONDS = 5.0
STOP_WAIT_SECONDS = 2.0
REAPER_INTERVAL_SECONDS = 15.0
COLS_DEFAULT, COLS_MIN, COLS_MAX = 200, 20, 500
ROWS_DEFAULT, ROWS_MIN, ROWS_MAX = 50, 5, 200
#: The code page a Korean Windows program answers in when it is not UTF-8.
FALLBACK_OUTPUT_ENCODING = "cp949"

_REQUEST_ID = re.compile(r"req_([0-9a-f]{32})\Z")
_SESSION_ID = re.compile(r"[0-9a-f]{32}\Z")


class SessionRefusal(Exception):
    """One session-level refusal: a contract code and a short English detail."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


# ---------------------------------------------------------------------------
# Output: bytes → text → a bounded buffer addressed by absolute offset.
# ---------------------------------------------------------------------------
class OutputDecoder:
    """What a program wrote, as text: UTF-8 first, the PC's code page second.

    A pipe carries whatever bytes the program chose. Each chunk is tried as
    UTF-8; a chunk that is not UTF-8 is read in the fallback code page from its
    first invalid byte on, and the next chunk is tried as UTF-8 again. A
    character split across two chunks is carried over rather than replaced.
    """

    def __init__(self, fallback: str = FALLBACK_OUTPUT_ENCODING) -> None:
        self._utf8 = codecs.getincrementaldecoder("utf-8")("strict")
        self._fallback = codecs.getincrementaldecoder(fallback)("replace")
        self._carry = b""
        self.fallback_used = False

    def feed(self, data: bytes, final: bool = False) -> str:
        if self._carry:
            data = self._carry + data
            self._carry = b""
        try:
            return self._utf8.decode(data, final)
        except UnicodeDecodeError as bad:
            # ``bad.object`` is the decoder's held bytes plus this chunk; its
            # state is unchanged by the failed call, so nothing is lost.
            whole = bytes(bad.object)
            self._utf8.reset()
            self.fallback_used = True
            head = whole[:bad.start].decode("utf-8")
            tail = self._fallback.decode(whole[bad.start:], final)
            if not final:
                pending = self._fallback.getstate()[0]
                self._carry = bytes(pending) if isinstance(pending, (bytes, bytearray)) else b""
            self._fallback.reset()
            return head + tail


@dataclass(frozen=True, slots=True)
class OutputSlice:
    """One read of the buffer. Offsets are absolute; ``data`` is whole characters."""

    data: bytes
    offset: int
    next_offset: int
    end_offset: int
    dropped_bytes: int


class OutputBuffer:
    """The last ``capacity`` bytes of a session's output, as UTF-8.

    Offsets never restart: ``end_offset`` is everything the program has printed
    so far, and the front of the buffer moves forward when it overflows. A read
    that asks for bytes already pushed out is told how many it missed.
    """

    def __init__(self, capacity: int = BUFFER_BYTES) -> None:
        self._capacity = max(16, int(capacity))
        self._data = bytearray()
        self._start = 0
        self._lock = threading.Lock()
        self._ends_with_newline = True
        #: ``time.monotonic()`` of the last append, or None before any output.
        self.last_append: float | None = None

    @property
    def end_offset(self) -> int:
        with self._lock:
            return self._start + len(self._data)

    @property
    def ends_with_newline(self) -> bool:
        with self._lock:
            return self._ends_with_newline

    def append(self, text: str) -> None:
        if not text:
            return
        encoded = text.encode("utf-8", errors="replace")
        with self._lock:
            self._data += encoded
            overflow = len(self._data) - self._capacity
            if overflow > 0:
                cut = overflow
                while cut < len(self._data) and (self._data[cut] & 0xC0) == 0x80:
                    cut += 1
                del self._data[:cut]
                self._start += cut
            self._ends_with_newline = encoded.endswith(b"\n")
            self.last_append = time.monotonic()

    def read(self, offset: int, length: int) -> OutputSlice:
        with self._lock:
            start, size = self._start, len(self._data)
            end = start + size
            dropped = 0
            if offset < start:
                dropped = start - offset
                offset = start
            if offset > end:
                offset = end
            begin = offset - start
            # A caller-chosen offset may point into a character: step forward
            # to the next lead byte so the slice always decodes.
            while begin < size and (self._data[begin] & 0xC0) == 0x80:
                begin += 1
            stop = min(size, begin + max(1, length))
            if stop < size:
                while stop > begin and (self._data[stop] & 0xC0) == 0x80:
                    stop -= 1
                if stop == begin:
                    # ``length`` is smaller than one character: return that
                    # whole character rather than nothing, so a pager advances.
                    stop = begin + 1
                    while stop < size and (self._data[stop] & 0xC0) == 0x80:
                        stop += 1
            return OutputSlice(
                data=bytes(self._data[begin:stop]),
                offset=start + begin,
                next_offset=start + stop,
                end_offset=end,
                dropped_bytes=dropped,
            )


# ---------------------------------------------------------------------------
# Windows: a kill-on-close job, so a session's process tree ends with the helper.
# ---------------------------------------------------------------------------
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _JobBasicLimit(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _JobExtendedLimit(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JobBasicLimit),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class WindowsKillOnCloseJob:
    """One job object per session. Closing or terminating it ends the tree.

    Creation or assignment can fail (an older Windows, a parent job that
    forbids nesting); the caller then ends the child with the handle it took
    at spawn time instead. A failure here never fails the session start.
    """

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise OSError("job objects exist on Windows only")
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.restype = ctypes.c_void_p
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        kernel.SetInformationJobObject.restype = ctypes.c_int
        kernel.SetInformationJobObject.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        kernel.AssignProcessToJobObject.restype = ctypes.c_int
        kernel.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        kernel.TerminateJobObject.restype = ctypes.c_int
        kernel.TerminateJobObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel.CloseHandle.restype = ctypes.c_int
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        self._kernel = kernel
        handle = kernel.CreateJobObjectW(None, None)
        if not handle:
            raise OSError(ctypes.get_last_error(), "the job object could not be created")
        self._handle: int | None = handle
        limits = _JobExtendedLimit()
        limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel.SetInformationJobObject(
                handle, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
                ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.get_last_error()
            self.close()
            raise OSError(error, "the job limit could not be set")

    def assign(self, process_handle: int) -> bool:
        if self._handle is None:
            return False
        return bool(self._kernel.AssignProcessToJobObject(self._handle, int(process_handle)))

    def terminate(self) -> bool:
        if self._handle is None:
            return False
        return bool(self._kernel.TerminateJobObject(self._handle, 1))

    def close(self) -> None:
        if self._handle is not None:
            self._kernel.CloseHandle(self._handle)
            self._handle = None


def _job_for(process_handle: Any) -> WindowsKillOnCloseJob | None:
    """Put one process in its own kill-on-close job, or report that it is not."""
    if sys.platform != "win32" or process_handle is None:
        return None
    try:
        job = WindowsKillOnCloseJob()
    except OSError:
        return None
    try:
        if job.assign(int(process_handle)):
            return job
    except (OSError, TypeError, ValueError):
        pass
    job.close()
    return None


# ---------------------------------------------------------------------------
# The process backend seam, and its anonymous-pipe implementation.
# ---------------------------------------------------------------------------
OutputCallback = Callable[[str], None]
ExitCallback = Callable[["int | None"], None]


class PipeBackend:
    """One program with its stdin, stdout and stderr on anonymous pipes.

    stderr is merged into stdout so the text keeps the order the program wrote
    it in. A program that sees a pipe does not believe it has a terminal: it
    may hold its prompt back, and it cannot be sent Ctrl+C. That is what the
    pseudo-terminal backend is for; this one is the portable floor.
    """

    name = BACKEND_PIPE
    #: Keys this backend can deliver. ``ctrl_d`` and ``ctrl_z`` both mean "no
    #: more input" on a pipe and close it.
    keys = frozenset({"enter", "tab", "esc", "ctrl_d", "ctrl_z"})
    #: How long the exit waits for the last output before it is reported. A
    #: grandchild that kept the pipe open must not hold the exit back.
    DRAIN_GRACE_SECONDS = 2.0

    def __init__(self, argv: Sequence[str], cwd: str | None, *,
                 on_output: OutputCallback, on_exit: ExitCallback,
                 input_encoding: str = "utf-8", **_unused: Any) -> None:
        self._on_output = on_output
        self._on_exit = on_exit
        self._input_encoding = input_encoding
        self._decoder = OutputDecoder()
        self._stdin_lock = threading.Lock()
        self._drained = threading.Event()
        # ``subprocess.Popen`` is looked up at call time on purpose: the packaged
        # helper replaces it with a seam that hides the child's console window.
        self._process = subprocess.Popen(  # noqa: S603 - argv is built from validated parts
            list(argv), cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, bufsize=0,
        )
        self._job = _job_for(getattr(self._process, "_handle", None))
        threading.Thread(target=self._pump, daemon=True,
                         name="padiem-session-output").start()
        threading.Thread(target=self._wait, daemon=True,
                         name="padiem-session-exit").start()

    def _pump(self) -> None:
        stream = self._process.stdout
        try:
            while True:
                chunk = stream.read(READ_MAX_BYTES)
                if not chunk:
                    break
                text = self._decoder.feed(chunk)
                if text:
                    self._on_output(text)
            tail = self._decoder.feed(b"", final=True)
            if tail:
                self._on_output(tail)
        except (OSError, ValueError):
            pass
        finally:
            self._drained.set()

    def _wait(self) -> None:
        code = self._process.wait()
        self._drained.wait(self.DRAIN_GRACE_SECONDS)
        self._on_exit(code)

    def supports_key(self, key: str) -> bool:
        return key in self.keys

    def _write(self, data: bytes) -> None:
        with self._stdin_lock:
            stream = self._process.stdin
            if stream is None or stream.closed:
                raise BrokenPipeError("the program's input is closed")
            view = memoryview(data)
            while view:
                written = stream.write(view)
                if not written:
                    raise BrokenPipeError("the program's input took no bytes")
                view = view[written:]

    def send_text(self, text: str, enter: bool) -> None:
        if enter:
            text += "\n"
        self._write(text.encode(self._input_encoding, errors="replace"))

    def send_key(self, key: str) -> None:
        if key in ("ctrl_d", "ctrl_z"):
            with self._stdin_lock:
                stream = self._process.stdin
                if stream is not None and not stream.closed:
                    stream.close()
            return
        self._write({"enter": b"\n", "tab": b"\t", "esc": b"\x1b"}[key])

    def poll(self) -> int | None:
        return self._process.poll()

    def terminate(self) -> None:
        if self._job is not None:
            self._job.terminate()
        try:
            self._process.kill()
        except OSError:
            pass

    def close(self) -> None:
        """Release what the backend holds once the program is gone."""
        for stream in (self._process.stdin, self._process.stdout):
            try:
                if stream is not None and not stream.closed:
                    stream.close()
            except OSError:
                pass
        if self._job is not None:
            self._job.close()
            self._job = None


def _terminal_powershell_script(command: str) -> str:
    """The script for a PowerShell command on a pseudo-terminal.

    The console's own code page is left alone there (the console host already
    answers in UTF-8), so only the exit code rule is added.
    """
    return (
        "$ProgressPreference='SilentlyContinue'\n"
        + command
        + "\n$__padiem_exit=0\n"
        "if($null -ne $LASTEXITCODE){$__padiem_exit=[int]$LASTEXITCODE}\n"
        "exit $__padiem_exit\n"
    )


def build_session_argv(shell: str, command: str, *, terminal: bool) -> list[str]:
    """The argv of one session's program, built from validated parts only.

    With a command the program is that command run through the chosen shell,
    and the session ends when it ends. With an empty command the program is
    the shell itself, interactive. Unlike a stage-2 request the PowerShell here
    is not ``-NonInteractive``: a session exists to be asked questions.

    The system executables are named by the full path the OS reported — the
    same rule the command requests follow — and a path that cannot be proven
    is a refusal, never a bare name.
    """
    if shell == SHELL_POWERSHELL:
        executable = windows_powershell_executable()
        if executable is None:
            raise UserHelperError(USER_HELPER_REFUSED,
                                  "the system directory location of powershell.exe could not be proven")
        base = [executable, "-NoProfile", "-NoLogo", "-ExecutionPolicy", "Bypass"]
        if command:
            script = (_terminal_powershell_script(command) if terminal
                      else powershell_envelope(command))
            encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
            return base + ["-EncodedCommand", encoded]
        # On a pipe PowerShell has no prompt loop of its own; ``-Command -``
        # is the mode that runs each line as it arrives.
        return base if terminal else base + ["-Command", "-"]
    if shell == SHELL_CMD:
        executable = system_executable("cmd.exe")
        if executable is None:
            raise UserHelperError(USER_HELPER_REFUSED,
                                  "the system directory location of cmd.exe could not be proven")
        return [executable, "/d", "/s", "/c", command] if command else [executable, "/d"]
    if shell == SHELL_BASH:
        bash = locate_git_bash()
        if bash is None:
            raise UserHelperError(USER_HELPER_BASH_MISSING,
                                  "no Git Bash through registry, PATH git.exe or standard roots")
        return [bash, "-lc", command] if command else [bash, "--login", "-i"]
    raise SessionRefusal(PC_SESSION_BAD_REQUEST, "shell is not one a session runs")


def default_backends() -> dict[str, "BackendFactory"]:
    """Pipes always; the pseudo console where this PC has one."""
    backends: dict[str, BackendFactory] = {BACKEND_PIPE: PipeBackend}
    try:
        from .conpty_backend import ConptyBackend, conpty_available  # noqa: PLC0415
    except ImportError:
        return backends
    if conpty_available():
        backends[BACKEND_CONPTY] = ConptyBackend
    return backends


# ---------------------------------------------------------------------------
# Replies.
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class SessionReply:
    """One operation's answer: the header object and the output text."""

    header: dict[str, Any]
    output: bytes = b""

    @property
    def ok(self) -> bool:
        return self.header.get("ok") is True

    @property
    def exit_code(self) -> int:
        """The frame's exit code: 0 for a done operation, 1 for a refusal."""
        return 0 if self.ok else 1

    def to_body(self) -> bytes:
        """Header line, a line feed, then the output. UTF-8 throughout."""
        head = json.dumps(self.header, ensure_ascii=True, separators=(",", ":"))
        return head.encode("ascii") + b"\n" + self.output


@dataclass
class _Session:
    session_id: str
    buffer: OutputBuffer
    keep_seconds: float
    last_contact: float
    backend: Any = None
    backend_name: str = BACKEND_PIPE
    input_encoding: str = "utf-8"
    secret_output: SecretOutputFilter = field(default_factory=SecretOutputFilter, repr=False)
    output_lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    ended: str | None = None
    exit_code: int | None = None
    ended_at: float | None = None
    exited: bool = False
    started_real: float = field(default_factory=time.monotonic)
    cond: threading.Condition = field(default_factory=threading.Condition)
    write_lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def alive(self) -> bool:
        return self.ended is None


# ---------------------------------------------------------------------------
# Operation document validation.
# ---------------------------------------------------------------------------
_START_KEYS = frozenset({"v", "op", "shell", "command", "terminal", "cols", "rows",
                         "keep_minutes", "input_encoding", "wait_ms"})
_INPUT_KEYS = frozenset({"v", "op", "session", "text_b64", "enter", "key", "secret",
                         "offset", "length", "wait_ms"})
_READ_KEYS = frozenset({"v", "op", "session", "offset", "length", "wait_ms"})
_STOP_KEYS = frozenset({"v", "op", "session", "offset", "length"})
_STATUS_KEYS = frozenset({"v", "op"})
_KEYS_BY_OP = {OP_START: _START_KEYS, OP_INPUT: _INPUT_KEYS, OP_READ: _READ_KEYS,
               OP_STOP: _STOP_KEYS, OP_STATUS: _STATUS_KEYS}


def decode_document(command: Any) -> dict[str, Any]:
    """The operation document carried in the frame's ``command`` field.

    Standard Base64 of one UTF-8 JSON object. Anything else is a bad request,
    reported in the reply header like every other session-level refusal.
    """
    if not isinstance(command, str) or not command:
        raise SessionRefusal(PC_SESSION_BAD_REQUEST, "the operation document is missing")
    try:
        raw = base64.b64decode(command, validate=True)
        document = json.loads(raw.decode("utf-8"))
    except Exception as bad:  # noqa: BLE001 - every decode failure is one refusal
        raise SessionRefusal(PC_SESSION_BAD_REQUEST,
                             "the operation document is not Base64 JSON") from bad
    if not isinstance(document, dict):
        raise SessionRefusal(PC_SESSION_BAD_REQUEST, "the operation document is not an object")
    return document


def _bad(detail: str) -> SessionRefusal:
    return SessionRefusal(PC_SESSION_BAD_REQUEST, detail)


def _integer(document: Mapping[str, Any], key: str, default: int | None,
             low: int, high: int) -> int | None:
    if key not in document or document[key] is None:
        return default
    value = document[key]
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise _bad(f"{key} is out of range")
    return value


def _boolean(document: Mapping[str, Any], key: str, default: bool) -> bool:
    if key not in document:
        return default
    value = document[key]
    if not isinstance(value, bool):
        raise _bad(f"{key} must be true or false")
    return value


def _session_id(document: Mapping[str, Any]) -> str:
    value = document.get("session")
    if not isinstance(value, str) or _SESSION_ID.fullmatch(value) is None:
        raise _bad("session is not a session number")
    return value


def _input_text(document: Mapping[str, Any]) -> str | None:
    token = document.get("text_b64")
    if token is None or token == "":
        return None
    if not isinstance(token, str):
        raise _bad("text_b64 is not text")
    try:
        text = base64.b64decode(token, validate=True).decode("utf-8")
    except Exception as bad:  # noqa: BLE001 - every decode failure is one refusal
        raise _bad("text_b64 is not Base64 UTF-8") from bad
    if len(text) > MAX_INPUT_CHARS:
        raise _bad("the input text is too long")
    if "\x00" in text or "\r" in text:
        raise _bad("the input text carries a reserved character")
    return text or None


# ---------------------------------------------------------------------------
# The manager.
# ---------------------------------------------------------------------------
ArgvBuilder = Callable[..., "list[str]"]
BackendFactory = Callable[..., Any]


class SessionManager:
    """Every session of one helper run.

    ``argv_builder``, ``backends`` and ``clock`` are seams: tests run the real
    logic over a small echo program and a clock they move, and the
    pseudo-terminal backend registers itself under :data:`BACKEND_CONPTY`.
    ``clock`` only measures contact and expiry; output waits use real time.
    """

    def __init__(self, *, argv_builder: ArgvBuilder = build_session_argv,
                 backends: Mapping[str, BackendFactory] | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 max_sessions: int = MAX_SESSIONS,
                 buffer_bytes: int = BUFFER_BYTES,
                 settle_ms: int = SETTLE_MS,
                 input_write_timeout: float = INPUT_WRITE_TIMEOUT_SECONDS,
                 reaper_interval: float | None = REAPER_INTERVAL_SECONDS) -> None:
        self._argv_builder = argv_builder
        self._backends: dict[str, BackendFactory] = dict(backends or default_backends())
        self._clock = clock
        self._max_sessions = max_sessions
        self._buffer_bytes = buffer_bytes
        self._settle = max(0.0, settle_ms / 1000.0)
        self._input_write_timeout = input_write_timeout
        self._lock = threading.RLock()
        self._sessions: dict[str, _Session] = {}
        self._closed = threading.Event()
        self._reaper: threading.Thread | None = None
        if reaper_interval is not None and reaper_interval > 0:
            self._reaper = threading.Thread(
                target=self._reap_loop, args=(float(reaper_interval),), daemon=True,
                name="padiem-session-reaper")
            self._reaper.start()

    # ---- public entry points ------------------------------------------
    @property
    def features(self) -> list[str]:
        """What this helper's sessions can do, for the ``status`` answer."""
        order = (BACKEND_PIPE, BACKEND_CONPTY)
        return [name for name in order if name in self._backends] + ["secret_mask"]

    def handle_command(self, command: Any, *, request_id: str,
                       cwd: str | None = None) -> SessionReply:
        """Decode the frame's ``command`` and answer the operation in it."""
        try:
            document = decode_document(command)
        except SessionRefusal as refused:
            return self._refusal(None, None, refused)
        return self.handle(document, request_id=request_id, cwd=cwd)

    def handle(self, document: Mapping[str, Any], *, request_id: str,
               cwd: str | None = None) -> SessionReply:
        """Answer one operation document. A refusal is a reply, never a raise."""
        op = document.get("op") if isinstance(document, Mapping) else None
        op_name = op if isinstance(op, str) and op in _KEYS_BY_OP else None
        session_hint = document.get("session") if isinstance(document, Mapping) else None
        session_hint = session_hint if isinstance(session_hint, str) and _SESSION_ID.fullmatch(
            session_hint) else None
        try:
            if not isinstance(document, Mapping):
                raise _bad("the operation document is not an object")
            if document.get("v") != SESSION_PROTOCOL_VERSION or isinstance(document.get("v"), bool):
                raise _bad("v is not a version this helper speaks")
            if op_name is None:
                raise _bad("op is not an operation")
            unknown = set(document) - _KEYS_BY_OP[op_name]
            if unknown:
                raise _bad("the operation carries an unknown field")
            self.reap()
            if op_name == OP_START:
                return self._start(document, request_id=request_id, cwd=cwd)
            if op_name == OP_INPUT:
                return self._input(document)
            if op_name == OP_READ:
                return self._read(document)
            if op_name == OP_STOP:
                return self._stop(document)
            return self._status()
        except SessionRefusal as refused:
            return self._refusal(op_name, session_hint, refused)

    def reap(self) -> None:
        """End sessions nobody has contacted, and forget long-ended ones."""
        now = self._clock()
        with self._lock:
            sessions = list(self._sessions.values())
        for session in sessions:
            if session.alive and now - session.last_contact > session.keep_seconds:
                self._end(session, ENDED_EXPIRED)
        with self._lock:
            ended = [s for s in self._sessions.values() if not s.alive]
            for session in ended:
                reference = max(session.ended_at or now, session.last_contact)
                if now - reference > ENDED_KEEP_SECONDS:
                    self._forget(session)
            ended = sorted((s for s in self._sessions.values() if not s.alive),
                           key=lambda s: s.ended_at or 0.0)
            for session in ended[:max(0, len(ended) - MAX_ENDED_SESSIONS)]:
                self._forget(session)

    def shutdown(self) -> None:
        """End every session. The helper calls this on its way out."""
        self._closed.set()
        with self._lock:
            sessions = list(self._sessions.values())
        for session in sessions:
            if session.alive:
                self._end(session, ENDED_STOPPED)
        with self._lock:
            for session in list(self._sessions.values()):
                self._forget(session)

    # ---- operations ---------------------------------------------------
    def _start(self, document: Mapping[str, Any], *, request_id: str,
               cwd: str | None) -> SessionReply:
        match = _REQUEST_ID.fullmatch(request_id) if isinstance(request_id, str) else None
        if match is None:
            raise _bad("request_id is not a request identifier")
        session_id = match.group(1)
        shell = document.get("shell", SHELL_POWERSHELL)
        if shell not in SESSION_SHELLS:
            raise _bad("shell is not one a session runs")
        command = document.get("command", "")
        if not isinstance(command, str) or len(command) > MAX_COMMAND_CHARS:
            raise _bad("command is not usable text")
        if command and not is_windows_shell_command(command):
            raise _bad("command is not a runnable command line")
        terminal = _boolean(document, "terminal", True)
        cols = _integer(document, "cols", COLS_DEFAULT, COLS_MIN, COLS_MAX)
        rows = _integer(document, "rows", ROWS_DEFAULT, ROWS_MIN, ROWS_MAX)
        keep = _integer(document, "keep_minutes", KEEP_DEFAULT_MINUTES, 1, KEEP_MAX_MINUTES)
        wait_ms = _integer(document, "wait_ms", WAIT_DEFAULT_MS, 0, WAIT_MAX_MS)
        input_encoding = document.get("input_encoding", INPUT_ENCODINGS[0])
        if input_encoding not in INPUT_ENCODINGS:
            raise _bad("input_encoding is not one a session writes")
        if cwd is None:
            # A start that names no folder used to inherit this helper's own
            # working directory — the install folder. The user's profile is
            # the default now; an undeterminable one is a failed start, never
            # the install folder back.
            cwd = default_working_directory()
        if not isinstance(cwd, str) or not os.path.isdir(cwd):
            raise SessionRefusal(PC_SESSION_START_FAILED, "cwd_invalid")

        with self._lock:
            if session_id in self._sessions:
                raise _bad("this session already exists")
            if sum(1 for s in self._sessions.values() if s.alive) >= self._max_sessions:
                raise SessionRefusal(PC_SESSION_LIMIT, "too many live sessions")
            session = _Session(
                session_id=session_id,
                buffer=OutputBuffer(self._buffer_bytes),
                keep_seconds=float(keep) * 60.0,
                last_contact=self._clock(),
                input_encoding=input_encoding,
            )
            # Reserved under the lock, so two starts cannot both pass the limit.
            self._sessions[session_id] = session
        try:
            self._spawn(session, shell=shell, command=command, cwd=cwd, terminal=terminal,
                        cols=cols, rows=rows, input_encoding=input_encoding)
        except BaseException:
            # A start that did not happen leaves no reserved slot behind.
            with self._lock:
                self._sessions.pop(session_id, None)
            raise
        self._wait_for_output(session, 0, wait_ms)
        return self._reply(session, OP_START, offset=0, length=READ_DEFAULT_BYTES)

    def _spawn(self, session: _Session, *, shell: str, command: str, cwd: str | None,
               terminal: bool, cols: int, rows: int, input_encoding: str) -> None:
        """Start the program on the best backend this helper has.

        A pseudo-terminal that cannot be opened is not a failed start: the
        program is started on pipes instead and the reply names the backend.
        """
        order = [BACKEND_PIPE]
        if terminal and BACKEND_CONPTY in self._backends:
            order.insert(0, BACKEND_CONPTY)
        failure = "spawn_failed"
        for name in order:
            factory = self._backends.get(name)
            if factory is None:
                continue
            try:
                argv = self._argv_builder(shell, command, terminal=(name == BACKEND_CONPTY))
            except UserHelperError as refused:
                detail = ("shell_unavailable" if refused.code == USER_HELPER_BASH_MISSING
                          else refused.code)
                raise SessionRefusal(PC_SESSION_START_FAILED, detail) from refused
            try:
                backend = factory(
                    argv, cwd, on_output=lambda text, s=session: self._on_output(s, text),
                    on_exit=lambda code, s=session: self._on_exit(s, code),
                    input_encoding=input_encoding, cols=cols, rows=rows,
                )
            except FileNotFoundError:
                failure = "shell_unavailable"
                continue
            except OSError:
                failure = "spawn_failed"
                continue
            session.backend = backend
            session.backend_name = getattr(backend, "name", name)
            return
        raise SessionRefusal(PC_SESSION_START_FAILED, failure)

    def _input(self, document: Mapping[str, Any]) -> SessionReply:
        session = self._find(_session_id(document))
        text = _input_text(document)
        enter = _boolean(document, "enter", True)
        secret = _boolean(document, "secret", False)
        key = document.get("key")
        if key is not None and key not in SESSION_KEYS:
            raise _bad("key is not one a session sends")
        if text is None and key is None:
            raise _bad("an input needs text_b64 or key")
        length = _integer(document, "length", READ_DEFAULT_BYTES, 1, READ_MAX_BYTES)
        wait_ms = _integer(document, "wait_ms", WAIT_DEFAULT_MS, 0, WAIT_MAX_MS)
        offset = _integer(document, "offset", None, 0, 2 ** 62)
        if offset is None:
            offset = session.buffer.end_offset
        if not session.alive:
            code = PC_SESSION_EXPIRED if session.ended == ENDED_EXPIRED else PC_SESSION_ENDED
            return self._reply(session, OP_INPUT, offset=offset, length=length,
                               code=code, detail="the program is not running")
        backend = session.backend
        if key is not None and not backend.supports_key(key):
            return self._reply(session, OP_INPUT, offset=offset, length=length,
                               code=PC_SESSION_KEY_UNSUPPORTED,
                               detail="this backend cannot send that key")

        def write() -> None:
            if text is not None:
                if secret:
                    with session.output_lock:
                        session.secret_output.register(
                            text, terminal=session.backend_name == BACKEND_CONPTY,
                            encoding=session.input_encoding)
                backend.send_text(text, enter)
            if key is not None:
                backend.send_key(key)

        refusal = self._write(session, write)
        if refusal is not None:
            return self._reply(session, OP_INPUT, offset=offset, length=length,
                               code=refusal.code, detail=refusal.detail)
        self._wait_for_output(session, offset, wait_ms)
        return self._reply(session, OP_INPUT, offset=offset, length=length)

    def _read(self, document: Mapping[str, Any]) -> SessionReply:
        session = self._find(_session_id(document))
        offset = _integer(document, "offset", 0, 0, 2 ** 62)
        length = _integer(document, "length", READ_DEFAULT_BYTES, 1, READ_MAX_BYTES)
        wait_ms = _integer(document, "wait_ms", 0, 0, WAIT_MAX_MS)
        if session.buffer.end_offset <= offset:
            self._wait_for_output(session, offset, wait_ms)
        return self._reply(session, OP_READ, offset=offset, length=length)

    def _stop(self, document: Mapping[str, Any]) -> SessionReply:
        session = self._find(_session_id(document))
        length = _integer(document, "length", READ_DEFAULT_BYTES, 1, READ_MAX_BYTES)
        offset = _integer(document, "offset", None, 0, 2 ** 62)
        if session.alive:
            self._end(session, ENDED_STOPPED)
        if offset is None:
            offset = session.buffer.end_offset
        return self._reply(session, OP_STOP, offset=offset, length=length)

    def _status(self) -> SessionReply:
        with self._lock:
            sessions = sorted(self._sessions.values(), key=lambda s: s.started_real)
        header = {
            "v": SESSION_PROTOCOL_VERSION, "ok": True, "code": None, "op": OP_STATUS,
            "limit": self._max_sessions, "features": self.features,
            "sessions": [{
                "session": s.session_id, "alive": s.alive, "ended": s.ended,
                "exit_code": s.exit_code, "backend": s.backend_name,
                "end_offset": s.buffer.end_offset, "idle_ms": self._idle_ms(s),
            } for s in sessions],
        }
        return SessionReply(header=header)

    # ---- internals ----------------------------------------------------
    def _find(self, session_id: str) -> _Session:
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise SessionRefusal(PC_SESSION_NOT_FOUND, "no such session on this PC")
        session.last_contact = self._clock()
        return session

    def _on_output(self, session: _Session, text: str) -> None:
        with session.output_lock:
            session.buffer.append(session.secret_output.feed(text))
        with session.cond:
            session.cond.notify_all()

    def _on_exit(self, session: _Session, code: int | None) -> None:
        with session.output_lock:
            session.buffer.append(session.secret_output.feed("", final=True))
        with session.cond:
            session.exited = True
            session.exit_code = code if isinstance(code, int) and not isinstance(code, bool) else None
            if session.ended is None:
                session.ended = ENDED_EXITED
                session.ended_at = self._clock()
            session.cond.notify_all()

    def _end(self, session: _Session, reason: str) -> None:
        """End a live session's program and wait a moment for its exit code."""
        with session.cond:
            if session.ended is not None:
                return
            session.ended = reason
            session.ended_at = self._clock()
            session.cond.notify_all()
        backend = session.backend
        if backend is not None:
            try:
                backend.terminate()
            except Exception:  # noqa: BLE001 - an ending must not raise into a reply
                pass
        deadline = time.monotonic() + STOP_WAIT_SECONDS
        with session.cond:
            while not session.exited:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                session.cond.wait(remaining)

    def _forget(self, session: _Session) -> None:
        self._sessions.pop(session.session_id, None)
        with session.output_lock:
            session.secret_output.feed("", final=True)
        closer = getattr(session.backend, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:  # noqa: BLE001 - cleanup is best effort
                pass

    def _write(self, session: _Session, action: Callable[[], None]) -> SessionRefusal | None:
        """Run one input write with a bound. An input is never sent twice."""
        if not session.write_lock.acquire(blocking=False):
            return SessionRefusal(PC_SESSION_INPUT_TIMEOUT, "an earlier input is still waiting")
        box: dict[str, bool] = {}

        def run() -> None:
            try:
                action()
            except BaseException as error:  # noqa: BLE001 - never retain input in an exception
                box["closed"] = isinstance(error, (OSError, ValueError))
            finally:
                session.write_lock.release()

        worker = threading.Thread(target=run, daemon=True, name="padiem-session-input")
        worker.start()
        worker.join(self._input_write_timeout)
        if worker.is_alive():
            return SessionRefusal(PC_SESSION_INPUT_TIMEOUT,
                                  "the program did not take the input in time")
        if not box:
            return None
        if box["closed"]:
            # The input end is gone: the program ended between the check and
            # the write. Give the exit a moment to be recorded.
            with session.cond:
                if not session.exited:
                    session.cond.wait(0.5)
            code = PC_SESSION_EXPIRED if session.ended == ENDED_EXPIRED else PC_SESSION_ENDED
            return SessionRefusal(code, "the program's input is closed")
        return SessionRefusal(PC_SESSION_INPUT_TIMEOUT, "the input could not be confirmed")

    def _wait_for_output(self, session: _Session, offset: int, wait_ms: int) -> None:
        """Wait until output past ``offset`` has settled, the program ended, or time is up."""
        if wait_ms <= 0:
            return
        deadline = time.monotonic() + wait_ms / 1000.0
        with session.cond:
            while True:
                now = time.monotonic()
                if session.exited or now >= deadline:
                    return
                remaining = deadline - now
                last = session.buffer.last_append
                if session.buffer.end_offset > offset and last is not None:
                    quiet = now - last
                    if quiet >= self._settle:
                        return
                    remaining = min(remaining, max(self._settle - quiet, 0.005))
                session.cond.wait(remaining)

    def _idle_ms(self, session: _Session) -> int:
        last = session.buffer.last_append
        reference = last if last is not None else session.started_real
        return max(0, int((time.monotonic() - reference) * 1000))

    def _reply(self, session: _Session, op: str, *, offset: int, length: int,
               code: str | None = None, detail: str | None = None) -> SessionReply:
        piece = session.buffer.read(offset, length)
        header: dict[str, Any] = {
            "v": SESSION_PROTOCOL_VERSION,
            "ok": code is None,
            "code": code,
            "op": op,
            "session": session.session_id,
            "alive": session.alive,
            "ended": session.ended,
            "exit_code": session.exit_code,
            "offset": piece.offset,
            "next_offset": piece.next_offset,
            "end_offset": piece.end_offset,
            "dropped_bytes": piece.dropped_bytes,
            "idle_ms": self._idle_ms(session),
            "ends_with_newline": session.buffer.ends_with_newline,
            "backend": session.backend_name,
        }
        end = session.buffer.end_offset
        tail = session.buffer.read(max(0, end - 1024), 1024).data.decode("utf-8")
        header.update(prompt_hints(tail, alive=session.alive,
                                   ends_with_newline=session.buffer.ends_with_newline))
        if detail:
            header["detail"] = detail
        return SessionReply(header=header, output=piece.data)

    def _refusal(self, op: str | None, session_id: str | None,
                 refused: SessionRefusal) -> SessionReply:
        header: dict[str, Any] = {
            "v": SESSION_PROTOCOL_VERSION, "ok": False, "code": refused.code,
            "op": op, "session": session_id,
        }
        if refused.detail:
            header["detail"] = refused.detail
        return SessionReply(header=header)

    def _reap_loop(self, interval: float) -> None:
        while not self._closed.wait(interval):
            try:
                self.reap()
            except Exception:  # noqa: BLE001 - the reaper must outlive one bad round
                pass


__all__ = [
    "BACKEND_CONPTY", "BACKEND_PIPE", "OutputBuffer", "OutputDecoder", "PipeBackend",
    "SESSION_PROTOCOL_VERSION", "SESSION_SHELL", "SessionManager", "SessionRefusal",
    "SessionReply", "build_session_argv", "decode_document", "default_backends",
]
