"""#7065 (c) stage 2 — the helper process that runs in the logged-in user session.

This is the entry point that actually runs as the interactive user. It opens the
local named pipe, accepts one request at a time, and hands every request to the
stage-1 contract in :mod:`claw_connect.user_session_helper`. Nothing about
validation is re-implemented here: ``parse_request``, ``verify_nonce``,
``ReplayGuard`` and ``serve_one`` are the stage-1 functions, called unchanged.

Three facts shape this module:

* **One request, one process — for commands.** A command request never reuses
  a child and never runs beside another command: ``serve_one`` enforces the
  process rule and one lock keeps commands serial. Since #7065 stage 3 each
  connection is served on its own thread, because a session operation
  (``shell=session``) is a short question to a program the helper already keeps
  and must be answered while a long command is still running.

* **The pipe is local and narrow.** ``\\\\.\\pipe\\padiem-user-helper-<device_id>``
  with an explicit DACL: SYSTEM and the one user this helper runs as. There is no
  network listener, no port, and nothing reachable from off the machine. The ACL
  is set at creation time rather than afterwards, so the pipe is never briefly
  open to everyone.

* **Frames are length-prefixed.** A pipe is a byte stream, and the agent keeps its
  end open to read the reply, so "read until EOF" would deadlock. Every frame is a
  4-byte big-endian length followed by that many bytes of JSON. The same framing
  is used by the SYSTEM side in :mod:`claw_connect.user_session_delegation`.

The helper is started at user logon by a scheduled task (ONLOGON, ``Limited``
run level) — see :mod:`claw_connect.user_helper_registration`. It is not a
service and it never runs as SYSTEM.
"""
from __future__ import annotations

import base64
import ctypes
import json
import os
import queue
import struct
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from .user_session_helper import (
    SHELL_SESSION,
    STAGE2_SHELLS,
    build_argv,
    HelperReply,
    ReplayGuard,
    Runner,
    UserHelperError,
    USER_HELPER_BAD_REPLY,
    USER_HELPER_BAD_REQUEST,
    USER_HELPER_REFUSED,
    USER_HELPER_TIMEOUT,
    error_reply,
    parse_request,
    pipe_name,
    run_process,
    serve_one,
    verify_nonce,
    working_directory,
)
from .user_session_manager import SessionManager, _job_for

#: Frame ceiling. A request is a command line plus a little metadata, and a reply
#: is two Base64 bodies; this bounds a malformed peer without bounding real work.
MAX_FRAME_BYTES = 2 * 1024 * 1024
#: #7106: a peer may connect and then say nothing (an executor restart, a killed
#: client). Without this window the helper sits in ReadFile forever, its single
#: accept slot stays occupied, and every later request queues behind a dead one.
REQUEST_READ_TIMEOUT_SECONDS = 5.0
#: While a stage-2 command runs, the helper sends this heartbeat so the SYSTEM
#: client can tell "still working" from "helper died after accepting". The
#: heartbeat is about liveness, not about how long a command may run.
HEARTBEAT_SECONDS = 5.0
#: How long one accept waits before the loop re-checks its stop condition. A
#: helper that is asked to stop must not sit in a blocking accept forever.
ACCEPT_POLL_SECONDS = 0.5
#: The pipe's own buffer. Large enough for one frame, so a writer never blocks
#: mid-frame on a healthy connection.
PIPE_BUFFER_BYTES = 64 * 1024
#: #7107: one output frame carries at most this much raw stdout/stderr. The
#: 2 MiB frame cap is a chunk size, not a total-output cap.
STREAM_CHUNK_BYTES = 512 * 1024
#: #7065 stage 3: how many connections are served at once. One past this is
#: served by the accept loop itself, so a flood degrades to the old serial
#: behaviour instead of growing threads without bound.
MAX_CONNECTION_THREADS = 8


# ---------------------------------------------------------------------------
# Framing. One length prefix, one JSON body. Shared with the SYSTEM side.
# ---------------------------------------------------------------------------
def encode_frame(payload: dict[str, Any]) -> bytes:
    """Serialise one frame: 4-byte big-endian length, then UTF-8 JSON.

    ``ensure_ascii`` keeps the bytes ASCII, which is the same rule the stage-1
    reply frame follows: a codepage can never destroy an answer that is already
    ASCII on the wire.
    """
    body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    if len(body) > MAX_FRAME_BYTES:
        raise UserHelperError(USER_HELPER_BAD_REQUEST, "the frame is too large to send")
    return struct.pack(">I", len(body)) + body


def read_frame(read_exact: Callable[[int], bytes]) -> dict[str, Any]:
    """Read one frame using a caller-supplied exact-read.

    ``read_exact`` returns exactly the requested number of bytes or raises. A
    short read is a broken connection, not a short frame: a partial body must
    never be parsed as if it were complete.
    """
    header = read_exact(4)
    if len(header) != 4:
        raise UserHelperError(USER_HELPER_BAD_REPLY, "the frame header was cut short")
    (length,) = struct.unpack(">I", header)
    if length == 0 or length > MAX_FRAME_BYTES:
        raise UserHelperError(USER_HELPER_BAD_REPLY, "the frame length is out of range")
    body = read_exact(length)
    if len(body) != length:
        raise UserHelperError(USER_HELPER_BAD_REPLY, "the frame body was cut short")
    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception as bad:
        raise UserHelperError(USER_HELPER_BAD_REPLY, "the frame is not readable JSON") from bad
    if not isinstance(payload, dict):
        raise UserHelperError(USER_HELPER_BAD_REPLY, "the frame is not an object")
    return payload


# ---------------------------------------------------------------------------
# The connection seam. Tests supply their own; production uses the Windows pipe.
# ---------------------------------------------------------------------------
class Connection(Protocol):
    """One accepted pipe connection."""

    def read_exact(self, size: int) -> bytes: ...
    def write_all(self, data: bytes) -> None: ...
    def close(self) -> None: ...


class Listener(Protocol):
    """A pipe that yields one connection per request."""

    def accept(self, timeout_seconds: float) -> Connection | None: ...
    def close(self) -> None: ...


# ---------------------------------------------------------------------------
# Windows named pipe, created with an explicit DACL.
# ---------------------------------------------------------------------------
#: ``D:`` a DACL that grants nothing implicitly, then two explicit grants:
#: ``SY`` = LocalSystem (the agent that forwards), ``OW`` = the object owner,
#: which is the user this helper runs as. ``OW`` is used rather than a looked-up
#: SID because the owner of a pipe created by this process is exactly that user,
#: and it cannot drift from the account the task was registered for.
PIPE_SDDL = "D:(A;;GA;;;SY)(A;;GA;;;OW)"

_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_OPEN_EXISTING = 3
_PIPE_ACCESS_DUPLEX = 0x00000003
#: The flag that fails a create when any instance of the pipe name already
#: exists. Only the first instance of a listener carries it: later instances
#: of the same listener would fail against the listener's own open instance.
_FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000
_PIPE_TYPE_BYTE = 0x00000000
_PIPE_READMODE_BYTE = 0x00000000
_PIPE_WAIT = 0x00000000
_PIPE_REJECT_REMOTE_CLIENTS = 0x00000008
_PIPE_UNLIMITED_INSTANCES = 255
_ERROR_INVALID_PARAMETER = 87
_ERROR_PIPE_CONNECTED = 535
_ERROR_BROKEN_PIPE = 109
_ERROR_NO_DATA = 232
_ERROR_SEM_TIMEOUT = 121


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [
        ("nLength", ctypes.c_ulong),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", ctypes.c_int),
    ]


def _is_invalid_handle(handle: Any) -> bool:
    try:
        value = handle.value if hasattr(handle, "value") else int(handle)
    except Exception:
        return not handle
    return value in (0, -1, (1 << 64) - 1)


def _kernel32():
    if sys.platform != "win32":
        raise UserHelperError(USER_HELPER_REFUSED, "named pipes exist on Windows only")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    try:
        kernel.CreateNamedPipeW.restype = ctypes.c_void_p
        kernel.CreateNamedPipeW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong,
                                            ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
        kernel.ConnectNamedPipe.restype = ctypes.c_int
        kernel.ConnectNamedPipe.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        kernel.ReadFile.restype = ctypes.c_int
        kernel.ReadFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p]
        kernel.WriteFile.restype = ctypes.c_int
        kernel.WriteFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p]
        kernel.PeekNamedPipe.restype = ctypes.c_int
        kernel.PeekNamedPipe.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong,
                                         ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong), ctypes.c_void_p]
        kernel.CloseHandle.restype = ctypes.c_int
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.WaitNamedPipeW.restype = ctypes.c_int
        kernel.WaitNamedPipeW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong]
        kernel.CreateFileW.restype = ctypes.c_void_p
        kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p,
                                       ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
    except Exception:
        pass
    return kernel


def build_security_attributes(sddl: str = PIPE_SDDL):
    """Build the SECURITY_ATTRIBUTES that carry the pipe's DACL.

    Returns ``(attributes, descriptor)``. The descriptor is returned so the
    caller keeps it alive for as long as the attributes are in use: freeing it
    early would leave the pipe with a dangling security descriptor.
    """
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    try:
        advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = ctypes.c_int
        advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
            ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p,
        ]
    except Exception:
        pass
    descriptor = ctypes.c_void_p()
    converted = advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        ctypes.c_wchar_p(sddl), 1, ctypes.byref(descriptor), None,
    )
    if not converted:
        error = ctypes.get_last_error()
        raise UserHelperError(USER_HELPER_REFUSED, f"the pipe DACL could not be built (winerr={error})")
    attributes = _SecurityAttributes()
    attributes.nLength = ctypes.sizeof(_SecurityAttributes)
    attributes.lpSecurityDescriptor = descriptor
    attributes.bInheritHandle = 0
    return attributes, descriptor


class WindowsPipeConnection:
    """One connected pipe instance."""

    def __init__(self, handle: Any, release: Any = None) -> None:
        self._handle = handle
        self._kernel = _kernel32()
        # The listener that created this instance closes it, so it can keep
        # count of its own open instances (see ``WindowsPipeListener``).
        self._release = release

    def read_exact(self, size: int) -> bytes:
        buffer = ctypes.create_string_buffer(size)
        read = ctypes.c_ulong(0)
        ok = self._kernel.ReadFile(
            self._handle, buffer, size, ctypes.byref(read), None,
        )
        if not ok:
            error = ctypes.get_last_error()
            if error in (_ERROR_BROKEN_PIPE, _ERROR_NO_DATA):
                return b""
            raise UserHelperError(USER_HELPER_BAD_REPLY, f"the pipe read failed (winerr={error})")
        return buffer.raw[: read.value]

    def _available(self) -> int:
        """Bytes already in the pipe, without consuming them."""
        total = ctypes.c_ulong(0)
        ok = self._kernel.PeekNamedPipe(
            self._handle, None, 0, None, ctypes.byref(total), None,
        )
        if not ok:
            error = ctypes.get_last_error()
            if error in (_ERROR_BROKEN_PIPE, _ERROR_NO_DATA):
                return 0
            raise UserHelperError(
                USER_HELPER_BAD_REPLY, f"the pipe peek failed (winerr={error})")
        return total.value

    def read_exact_bounded(self, size: int) -> bytes:
        """Read one frame's bytes, or refuse if the peer stops mid-frame.

        The stage-2 client writes the 4-byte prefix and the body as two writes.
        A client killed between them used to leave the helper blocked in
        ``ReadFile`` for the rest of the body toward a hole that never fills.
        ``PeekNamedPipe`` lets this read the bytes that are already there and
        give up on a peer that stopped, so one half-frame cannot wedge the
        helper's only accept slot.
        """
        deadline = time.monotonic() + REQUEST_READ_TIMEOUT_SECONDS
        collected = bytearray()
        while len(collected) < size:
            available = self._available()
            if available <= 0:
                if time.monotonic() >= deadline:
                    raise UserHelperError(
                        USER_HELPER_TIMEOUT, "the request frame stopped mid-way")
                time.sleep(0.05)
                continue
            chunk = self.read_exact(min(available, size - len(collected)))
            if not chunk:
                raise UserHelperError(
                    USER_HELPER_BAD_REPLY, "the pipe closed before the frame was complete")
            collected.extend(chunk)
        return bytes(collected)

    def wait_readable(self, timeout_seconds: float) -> None:
        """Wait for the first byte of a frame, or refuse after the window.

        ``PeekNamedPipe`` is what makes this bounded without touching the
        blocking ``ReadFile`` below: a peer that connected and sent nothing is
        refused here, and the helper's serial accept loop moves on. A closed
        peer is a refusal with no reply, not a broken pipe that ends the loop.
        """
        deadline = time.monotonic() + float(timeout_seconds)
        while True:
            available = ctypes.c_ulong(0)
            ok = self._kernel.PeekNamedPipe(
                self._handle, None, 0, None, ctypes.byref(available), None,
            )
            if not ok:
                error = ctypes.get_last_error()
                if error in (_ERROR_BROKEN_PIPE, _ERROR_NO_DATA):
                    raise UserHelperError(
                        USER_HELPER_BAD_REPLY, "the pipe closed before a request arrived")
                raise UserHelperError(
                    USER_HELPER_BAD_REPLY, f"the pipe peek failed (winerr={error})")
            if available.value > 0:
                return
            if time.monotonic() >= deadline:
                raise UserHelperError(
                    USER_HELPER_TIMEOUT, "no request frame arrived in time")
            time.sleep(0.05)

    def peer_closed(self) -> bool:
        """Whether the client end is gone, without consuming a byte."""
        total = ctypes.c_ulong(0)
        ok = self._kernel.PeekNamedPipe(
            self._handle, None, 0, None, ctypes.byref(total), None,
        )
        if ok:
            return False
        return ctypes.get_last_error() in (_ERROR_BROKEN_PIPE, _ERROR_NO_DATA)

    def write_all(self, data: bytes) -> None:
        written = ctypes.c_ulong(0)
        ok = self._kernel.WriteFile(
            self._handle, data, len(data), ctypes.byref(written), None,
        )
        if not ok or written.value != len(data):
            error = ctypes.get_last_error()
            raise UserHelperError(USER_HELPER_BAD_REPLY, f"the pipe write failed (winerr={error})")

    def close(self) -> None:
        handle, self._handle = self._handle, None
        if handle and not _is_invalid_handle(handle):
            if self._release is not None:
                self._release(handle)
            else:
                self._kernel.CloseHandle(handle)


class WindowsPipeListener:
    """The helper's listening pipe: one instance per accepted request.

    A named pipe instance serves one connection, so each accept creates the next
    instance before returning. That is also what keeps the helper serial: there
    is never a second instance waiting while a request is being served.
    """

    def __init__(self, device_id: str, *, sddl: str = PIPE_SDDL) -> None:
        self._name = pipe_name(device_id)
        self._kernel = _kernel32()
        self._attributes, self._descriptor = build_security_attributes(sddl)
        # How many instances of the name this listener holds open right now:
        # the one waiting for a client plus every accepted connection still
        # being served (connections are served on worker threads). The name is
        # only safely ours while that count is above zero.
        self._live = 0
        self._live_lock = threading.Lock()
        self._first_instance = True
        self._handle = self._create_instance()

    def _release_instance(self, handle) -> None:
        """Close one of this listener's instances and count it out.

        Count and close happen under the same lock a create takes, so a create
        never sees "an instance is still open" for a handle that is already
        closed, nor the reverse.
        """
        with self._live_lock:
            self._kernel.CloseHandle(handle)
            self._live -= 1

    def _create_instance(self):
        with self._live_lock:
            return self._create_instance_locked()

    def _create_instance_locked(self):
        # Whenever this listener holds no open instance, the next create is a
        # "first instance" again, not only at start: if every instance was
        # closed (a failed pre-create followed by the last connection ending),
        # another local account could have created the name in the gap, and a
        # create without the flag would then join that account's pipe.
        self._first_instance = self._live == 0
        open_mode = _PIPE_ACCESS_DUPLEX
        if self._first_instance:
            # The first instance claims the name: if anything — another local
            # account's pre-created pipe, a second helper — already owns it,
            # the create fails and the helper refuses to start instead of
            # serving on somebody else's DACL.
            open_mode |= _FILE_FLAG_FIRST_PIPE_INSTANCE
        handle = self._kernel.CreateNamedPipeW(
            ctypes.c_wchar_p("\\\\.\\pipe\\" + self._name),
            open_mode,
            _PIPE_TYPE_BYTE | _PIPE_READMODE_BYTE | _PIPE_WAIT | _PIPE_REJECT_REMOTE_CLIENTS,
            _PIPE_UNLIMITED_INSTANCES,
            PIPE_BUFFER_BYTES,
            PIPE_BUFFER_BYTES,
            0,
            ctypes.byref(self._attributes),
        )
        if _is_invalid_handle(handle):
            error = ctypes.get_last_error()
            if self._first_instance:
                raise UserHelperError(
                    USER_HELPER_REFUSED,
                    f"the helper pipe name is already taken; not starting (winerr={error})")
            raise UserHelperError(USER_HELPER_REFUSED, f"the helper pipe could not be created (winerr={error})")
        self._live += 1
        self._first_instance = False
        return handle

    def accept(self, timeout_seconds: float) -> Connection | None:
        """Wait for one connection, or return ``None`` when the wait expired."""
        if self._handle is None or _is_invalid_handle(self._handle):
            self._handle = self._create_instance()
        connected = self._kernel.ConnectNamedPipe(self._handle, None)
        if not connected:
            error = ctypes.get_last_error()
            if error == _ERROR_PIPE_CONNECTED:
                # A client connected between create and connect: already served.
                pass
            elif error == _ERROR_SEM_TIMEOUT:
                return None
            else:
                raise UserHelperError(USER_HELPER_REFUSED, f"the pipe accept failed (winerr={error})")
        connection = WindowsPipeConnection(self._handle, release=self._release_instance)
        # The instance now belongs to the connection; prepare next if possible.
        self._handle = None
        try:
            self._handle = self._create_instance()
        except UserHelperError:
            # Do not fail the already-accepted connection; listener can recreate on next accept.
            self._handle = None
        return connection

    def close(self) -> None:
        handle, self._handle = self._handle, None
        if handle and not _is_invalid_handle(handle):
            self._release_instance(handle)


# ---------------------------------------------------------------------------
# The serve loop.
# ---------------------------------------------------------------------------
@dataclass
class ServeStats:
    """What one helper run actually did. Counts only, never command text."""

    served: int = 0
    refused: int = 0
    last_error: str = ""


class _FrameWriter:
    """One writer for one connection, shared by the serve thread and heartbeat.

    A start frame and a heartbeat go out while ``serve_one`` runs. Two threads
    writing frames interleaved would corrupt the 4-byte prefix, so every frame
    takes this lock; a failed write marks the peer gone and is never retried.
    """

    def __init__(self, connection: Connection) -> None:
        self._connection = connection
        self._lock = threading.Lock()
        self.gone = threading.Event()

    def send(self, payload: dict[str, Any]) -> bool:
        with self._lock:
            if self.gone.is_set():
                return False
            try:
                self._connection.write_all(encode_frame(payload))
                return True
            except Exception:
                self.gone.set()
                return False


def _heartbeat_frames(writer: _FrameWriter, request_id: str, stop: threading.Event) -> None:
    """Say "still working" until the command ends or the peer disappears."""
    count = 0
    while not stop.wait(HEARTBEAT_SECONDS):
        count += 1
        if not writer.send({
            "request_id": request_id, "status": "running", "heartbeat": count,
        }):
            return


def handle_connection(connection: Connection, *, secret: bytes,
                      guard: ReplayGuard, runner: Runner = run_process,
                      sessions: SessionManager | None = None,
                      command_lock: Any = None) -> str:
    """Serve exactly one request on one connection and close it.

    Returns the outcome label for the caller's counter. The request is parsed and
    authenticated by the stage-1 functions; a frame that fails either check
    produces a refusal reply and no process.

    ``sessions`` answers ``shell=session`` requests; without one they are
    refused. ``command_lock`` is what keeps command requests serial now that
    connections have their own threads: a command waits for it, a session
    operation never does.
    """
    request_id = ""
    try:
        # #7106: a connection that never sends a frame is the stale half-open
        # peer that used to wedge the helper forever. Refuse it with no reply so
        # the next request can be accepted; fakes without the seam keep the old
        # behaviour and are only used by unit tests.
        waiter = getattr(connection, "wait_readable", None)
        if callable(waiter):
            try:
                waiter(REQUEST_READ_TIMEOUT_SECONDS)
            except UserHelperError:
                return "refused"
        bounded = getattr(connection, "read_exact_bounded", None)
        payload = read_frame(bounded if callable(bounded) else connection.read_exact)
        request_id = str(payload.get("request_id", ""))
        request = parse_request(payload)
        if not verify_nonce(secret, request):
            reply = error_reply(request.request_id, USER_HELPER_REFUSED,
                                detail="the request nonce did not verify")
            connection.write_all(encode_frame(reply.to_frame()))
            return "refused"
        if not guard.accept(request.request_id):
            reply = error_reply(request.request_id, USER_HELPER_REFUSED,
                                detail="this request id was already served")
            connection.write_all(encode_frame(reply.to_frame()))
            return "refused"
        if request.shell == SHELL_SESSION:
            return _serve_session(connection, request, sessions)
        if command_lock is not None:
            with command_lock:
                if _peer_closed(connection):
                    # The client gave up while this command waited its turn.
                    # A command nobody is waiting for is not started at all.
                    return "refused"
                return _serve_command(connection, request, secret=secret, runner=runner)
        return _serve_command(connection, request, secret=secret, runner=runner)
    except UserHelperError as refused:
        # A malformed frame still gets an answer when the request id is known,
        # so the agent is never left waiting on a pipe that will not speak.
        try:
            reply = error_reply(request_id, refused.code, detail=refused.detail)
            connection.write_all(encode_frame(reply.to_frame()))
        except Exception:
            pass
        return "refused"
    finally:
        connection.close()


def _serve_session(connection: Connection, request,
                   sessions: SessionManager | None) -> str:
    """Answer one session operation in one final frame.

    The manager's reply — a header line, then the output — is the frame's
    ``stdout_b64``, and its 0/1 is the frame's ``exit_code``. That is the
    shape the SYSTEM client already relays unchanged, so a session operation
    needs nothing new on that side. A session-level refusal is still a
    ``status: ok`` frame: only a helper that cannot answer at all refuses the
    frame itself.
    """
    started = time.monotonic()
    if sessions is None:
        reply = error_reply(request.request_id, USER_HELPER_REFUSED,
                            detail="sessions are not available on this helper")
    else:
        try:
            answer = sessions.handle_command(
                request.command, request_id=request.request_id, cwd=request.cwd)
        except Exception:  # noqa: BLE001 - one bad operation must not end the helper
            reply = error_reply(request.request_id, USER_HELPER_REFUSED,
                                detail="the session operation failed")
        else:
            reply = HelperReply(
                request_id=request.request_id, status="ok", exit_code=answer.exit_code,
                stdout=answer.to_body(),
                duration_ms=int((time.monotonic() - started) * 1000),
            )
    connection.write_all(encode_frame(reply.to_frame()))
    return "served" if reply.status == "ok" else "refused"


def _serve_command(connection: Connection, request, *, secret: bytes,
                   runner: Runner) -> str:
    """Run one command request: the stage-1 and stage-2 paths, unchanged."""
    if request.shell in STAGE2_SHELLS:
        # #7107: production stage-2 commands stream their output and run
        # without a deadline. Tests that inject a runner keep the one-shot
        # seam below, so their framing contract is unchanged.
        if runner is run_process:
            return _serve_streaming(connection, request)
        # #7106: the SYSTEM client must be able to distinguish "the helper
        # took the request and is working" from "the helper accepted and
        # died". A start frame goes out before the child exists, and a
        # heartbeat every few seconds until it exits; neither limits how
        # long the command itself may run.
        writer = _FrameWriter(connection)
        writer.send({"request_id": request.request_id, "status": "started"})
        stop = threading.Event()
        pulses = threading.Thread(
            target=_heartbeat_frames, args=(writer, request.request_id, stop),
            daemon=True,
        )
        pulses.start()
        try:
            reply = serve_one(request, secret=secret, runner=runner)
        finally:
            stop.set()
            pulses.join(timeout=1)
        writer.send(reply.to_frame())
    else:
        reply = serve_one(request, secret=secret, runner=runner)
        connection.write_all(encode_frame(reply.to_frame()))
    return "served" if reply.status == "ok" else "refused"


def _peer_closed(connection: Connection) -> bool:
    """Whether the SYSTEM peer has already gone away."""
    probe = getattr(connection, "peer_closed", None)
    try:
        return bool(probe()) if callable(probe) else False
    except Exception:
        return True


def _kill_process_tree(process: subprocess.Popen) -> None:
    """End the command and its children — by job, else by the spawn handle.

    The job ends every process the child started, however PIDs were reused in
    the meantime. Without a job, ``Popen.kill`` is still ``TerminateProcess``
    on the handle taken at creation, so a recycled PID cannot redirect it.
    There is deliberately no ``taskkill /T`` here: it picks children by parent
    PID value, and a reused PID makes that somebody else's process tree.
    """
    job = getattr(process, "_padiem_job", None)
    if job is not None:
        try:
            if job.terminate():
                return
        except Exception:
            pass
    try:
        process.kill()
    except Exception:
        pass


def _serve_streaming(connection: Connection, request) -> str:
    """#7107: run one stage-2 command, stream its output, and never time it out.

    The connection is the owner's handle on the work. While it is alive the
    helper sends ``started``, a heartbeat every five seconds, and one frame per
    output chunk. If the owner stops the dispatch the SYSTEM client is killed,
    this helper sees the broken pipe, and the user child is ended too; the same
    broken pipe is why a mid-frame client can no longer leave an orphan here.
    """
    request_id = request.request_id
    writer = _FrameWriter(connection)
    writer.send({"request_id": request_id, "status": "started"})
    started = time.monotonic()
    try:
        argv = build_argv(request)
        process = subprocess.Popen(  # noqa: S603 - argv is built from validated parts
            argv, cwd=working_directory(request.cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            bufsize=0,
        )
    except UserHelperError as refused:
        writer.send(error_reply(request_id, refused.code, detail=refused.detail).to_frame())
        return "refused"
    except OSError as missing:
        writer.send(error_reply(request_id, USER_HELPER_REFUSED,
                                detail="the executable is not on this PC").to_frame())
        return "refused"
    # The child goes into its own kill-on-close job the moment it exists, so a
    # cancelled command ends its whole tree; without a job the spawn handle
    # still ends the child itself (see :func:`_kill_process_tree`).
    process._padiem_job = _job_for(getattr(process, "_handle", None))

    events: queue.Queue = queue.Queue()

    def pump(name: str, stream) -> None:
        try:
            while True:
                chunk = stream.read(STREAM_CHUNK_BYTES)
                if not chunk:
                    return
                events.put((name, chunk))
        finally:
            events.put((name, None))

    for name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
        threading.Thread(target=pump, args=(name, stream), daemon=True).start()

    stop = threading.Event()
    pulses = threading.Thread(
        target=_heartbeat_frames, args=(writer, request_id, stop), daemon=True,
    )
    pulses.start()
    pending = 2
    stdout_bytes = stderr_bytes = 0
    cancelled = False
    try:
        while True:
            if not cancelled and writer.gone.is_set():
                # The owner stopped the dispatch or the executor restarted. The
                # heartbeat write is the reliable death signal: a killed client
                # closes the pipe and the next 5s write fails. The child belongs
                # to this helper, so end it instead of leaving an orphan.
                cancelled = True
                _kill_process_tree(process)
            try:
                name, chunk = events.get(timeout=0.2)
            except queue.Empty:
                if process.poll() is not None and pending == 0:
                    break
                continue
            if chunk is None:
                pending -= 1
                if process.poll() is not None and pending == 0:
                    break
                continue
            if name == "stdout":
                stdout_bytes += len(chunk)
            else:
                stderr_bytes += len(chunk)
            writer.send({
                "request_id": request_id, "status": name,
                "data_b64": base64.b64encode(chunk).decode("ascii"),
            })
        exit_code = process.wait()
    finally:
        stop.set()
        pulses.join(timeout=1)
        if process.poll() is None:
            _kill_process_tree(process)
        job = getattr(process, "_padiem_job", None)
        if job is not None:
            # Kill-on-close: closing the last job handle ends anything the
            # child left behind, and the child is gone by now.
            job.close()
    final = {
        "request_id": request_id,
        "status": "cancelled" if cancelled else "ok",
        "exit_code": exit_code,
        "stdout_bytes": stdout_bytes,
        "stderr_bytes": stderr_bytes,
        "truncated": False,
        "duration_ms": int((time.monotonic() - started) * 1000),
    }
    return "served" if writer.send(final) and not cancelled else "refused"


def serve_pipe(*, device_id: str, secret: bytes, listener: Listener | None = None,
               runner: Runner = run_process, max_requests: int | None = None,
               should_stop: Callable[[], bool] | None = None,
               sessions: SessionManager | None = None) -> ServeStats:
    """Accept and serve requests until stopped.

    ``max_requests`` and ``should_stop`` exist so a test can run the real loop
    over a fake listener, and so the shipped helper can be asked to stop without
    being killed. Neither changes how a request is served.

    #7065 stage 3: each accepted connection is served on its own thread (up to
    ``MAX_CONNECTION_THREADS``), commands stay serial behind one lock, and the
    loop owns the session manager for this run: when the loop ends, every
    session it kept is ended with it. The returned counts cover every
    connection the loop accepted — it waits for the ones still being served.
    """
    if not isinstance(secret, (bytes, bytearray)) or not secret:
        raise UserHelperError(USER_HELPER_REFUSED, "the helper has no deployment secret")
    own_listener = listener is None
    active = listener or WindowsPipeListener(device_id)
    own_sessions = sessions is None
    session_manager = sessions if sessions is not None else SessionManager()
    guard = ReplayGuard()
    stats = ServeStats()
    command_lock = threading.Lock()
    slots = threading.BoundedSemaphore(MAX_CONNECTION_THREADS)
    counter_lock = threading.Lock()
    in_flight = [0]
    workers: list[threading.Thread] = []

    def serve(connection: Connection, threaded: bool) -> None:
        try:
            outcome = handle_connection(
                connection, secret=bytes(secret), guard=guard, runner=runner,
                sessions=session_manager, command_lock=command_lock)
        except Exception:  # noqa: BLE001 - one broken connection must not end the helper
            outcome = "refused"
        with counter_lock:
            if outcome == "served":
                stats.served += 1
            else:
                stats.refused += 1
            in_flight[0] -= 1
        if threaded:
            slots.release()

    try:
        while True:
            if should_stop is not None and should_stop():
                break
            with counter_lock:
                begun = stats.served + stats.refused + in_flight[0]
            if max_requests is not None and begun >= max_requests:
                break
            try:
                connection = active.accept(ACCEPT_POLL_SECONDS)
            except UserHelperError as refused:
                stats.last_error = f"{refused.code}: {refused.detail}" if refused.detail else refused.code
                break
            if connection is None:
                continue
            with counter_lock:
                in_flight[0] += 1
            if slots.acquire(blocking=False):
                worker = threading.Thread(target=serve, args=(connection, True), daemon=True,
                                          name="padiem-helper-connection")
                workers = [item for item in workers if item.is_alive()]
                workers.append(worker)
                worker.start()
            else:
                serve(connection, False)
    finally:
        for worker in workers:
            worker.join()
        if own_sessions:
            session_manager.shutdown()
        if own_listener:
            active.close()
    return stats


def load_secret(path: str | None = None) -> bytes:
    """Read the PC's deployment secret for HMAC keying.

    The secret is read from the file the installer wrote, and its value is never
    printed, logged or returned to a caller that would show it. A missing or
    empty secret is a refusal: the helper will not run unauthenticated.
    """
    source = path or os.environ.get("PADIEM_USER_HELPER_SECRET_FILE", "")
    if not source:
        raise UserHelperError(USER_HELPER_REFUSED, "no deployment secret file is configured")
    try:
        with open(source, "rb") as handle:
            secret = handle.read().strip()
    except OSError as missing:
        raise UserHelperError(USER_HELPER_REFUSED, "the deployment secret file is unreadable") from missing
    if not secret:
        raise UserHelperError(USER_HELPER_REFUSED, "the deployment secret is empty")
    return secret


def main(argv: list[str] | None = None) -> int:
    """``python -m claw_connect.user_helper_service --device-id <id>``

    Exit codes are the only thing printed: the helper writes no command text and
    no secret to its own console, because that console is the user's session.
    """
    import argparse  # noqa: PLC0415 - keeps the module import cheap for tests

    parser = argparse.ArgumentParser(prog="claw_connect.user_helper_service")
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--secret-file", default=None)
    parser.add_argument("--max-requests", type=int, default=None)
    args = parser.parse_args(argv)
    try:
        secret = load_secret(args.secret_file)
        stats = serve_pipe(device_id=args.device_id, secret=secret,
                           max_requests=args.max_requests)
    except UserHelperError as refused:
        detail = f" {refused.detail}" if refused.detail else ""
        print(f"refused:{refused.code}{detail}", file=sys.stderr)
        return 2
    if stats.last_error:
        print(f"refused:{stats.last_error}", file=sys.stderr)
        return 2
    print(f"served={stats.served} refused={stats.refused}")
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
