"""#7065 (c) stage 2 — the helper process that runs in the logged-in user session.

This is the entry point that actually runs as the interactive user. It opens the
local named pipe, accepts one request at a time, and hands every request to the
stage-1 contract in :mod:`claw_connect.user_session_helper`. Nothing about
validation is re-implemented here: ``parse_request``, ``verify_nonce``,
``ReplayGuard`` and ``serve_one`` are the stage-1 functions, called unchanged.

Three facts shape this module:

* **One request, one process.** The helper never reuses a child, never keeps a
  shell warm and never runs two requests at once. ``serve_one`` already enforces
  the process rule; this module enforces the serial rule by accepting, serving
  and closing one connection before it accepts the next.

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

import ctypes
import json
import os
import struct
import sys
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from .user_session_helper import (
    MAX_STREAM_BYTES,
    ReplayGuard,
    Runner,
    UserHelperError,
    USER_HELPER_BAD_REPLY,
    USER_HELPER_BAD_REQUEST,
    USER_HELPER_REFUSED,
    error_reply,
    parse_request,
    pipe_name,
    run_process,
    serve_one,
    verify_nonce,
)

#: Frame ceiling. A request is a command line plus a little metadata, and a reply
#: is two Base64 bodies; this bounds a malformed peer without bounding real work.
MAX_FRAME_BYTES = 2 * 1024 * 1024
#: How long one accept waits before the loop re-checks its stop condition. A
#: helper that is asked to stop must not sit in a blocking accept forever.
ACCEPT_POLL_SECONDS = 0.5
#: The pipe's own buffer. Large enough for one frame, so a writer never blocks
#: mid-frame on a healthy connection.
PIPE_BUFFER_BYTES = 64 * 1024


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
_PIPE_TYPE_BYTE = 0x00000000
_PIPE_WAIT = 0x00000000
_PIPE_REJECT_REMOTE_CLIENTS = 0x00000008
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
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


def _kernel32():
    if sys.platform != "win32":
        raise UserHelperError(USER_HELPER_REFUSED, "named pipes exist on Windows only")
    return ctypes.WinDLL("kernel32", use_last_error=True)


def build_security_attributes(sddl: str = PIPE_SDDL):
    """Build the SECURITY_ATTRIBUTES that carry the pipe's DACL.

    Returns ``(attributes, descriptor)``. The descriptor is returned so the
    caller keeps it alive for as long as the attributes are in use: freeing it
    early would leave the pipe with a dangling security descriptor.
    """
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    descriptor = ctypes.c_void_p()
    converted = advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        ctypes.c_wchar_p(sddl), 1, ctypes.byref(descriptor), None,
    )
    if not converted:
        raise UserHelperError(USER_HELPER_REFUSED, "the pipe DACL could not be built")
    attributes = _SecurityAttributes()
    attributes.nLength = ctypes.sizeof(_SecurityAttributes)
    attributes.lpSecurityDescriptor = descriptor
    attributes.bInheritHandle = 0
    return attributes, descriptor


class WindowsPipeConnection:
    """One connected pipe instance."""

    def __init__(self, handle: Any) -> None:
        self._handle = handle
        self._kernel = _kernel32()

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
            raise UserHelperError(USER_HELPER_BAD_REPLY, "the pipe read failed")
        return buffer.raw[: read.value]

    def write_all(self, data: bytes) -> None:
        written = ctypes.c_ulong(0)
        ok = self._kernel.WriteFile(
            self._handle, data, len(data), ctypes.byref(written), None,
        )
        if not ok or written.value != len(data):
            raise UserHelperError(USER_HELPER_BAD_REPLY, "the pipe write failed")

    def close(self) -> None:
        if self._handle:
            self._kernel.CloseHandle(self._handle)
            self._handle = None


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
        self._handle = self._create_instance()

    def _create_instance(self):
        handle = self._kernel.CreateNamedPipeW(
            ctypes.c_wchar_p("\\\\.\\pipe\\" + self._name),
            _PIPE_ACCESS_DUPLEX | _PIPE_REJECT_REMOTE_CLIENTS,
            _PIPE_TYPE_BYTE | _PIPE_WAIT,
            1,                      # one instance: the helper is serial
            PIPE_BUFFER_BYTES,
            PIPE_BUFFER_BYTES,
            0,
            ctypes.byref(self._attributes),
        )
        if handle == _INVALID_HANDLE_VALUE or not handle:
            raise UserHelperError(USER_HELPER_REFUSED, "the helper pipe could not be created")
        return handle

    def accept(self, timeout_seconds: float) -> Connection | None:
        """Wait for one connection, or return ``None`` when the wait expired."""
        connected = self._kernel.ConnectNamedPipe(self._handle, None)
        if not connected:
            error = ctypes.get_last_error()
            if error == _ERROR_PIPE_CONNECTED:
                # A client connected between create and connect: already served.
                pass
            elif error == _ERROR_SEM_TIMEOUT:
                return None
            else:
                raise UserHelperError(USER_HELPER_REFUSED, "the pipe accept failed")
        connection = WindowsPipeConnection(self._handle)
        # The instance now belongs to the connection; the next accept creates a
        # fresh one, so the helper is never listening while it is serving.
        self._handle = self._create_instance()
        return connection

    def close(self) -> None:
        if self._handle:
            self._kernel.CloseHandle(self._handle)
            self._handle = None


# ---------------------------------------------------------------------------
# The serve loop.
# ---------------------------------------------------------------------------
@dataclass
class ServeStats:
    """What one helper run actually did. Counts only, never command text."""

    served: int = 0
    refused: int = 0
    last_error: str = ""


def handle_connection(connection: Connection, *, secret: bytes,
                      guard: ReplayGuard, runner: Runner = run_process) -> str:
    """Serve exactly one request on one connection and close it.

    Returns the outcome label for the caller's counter. The request is parsed and
    authenticated by the stage-1 functions; a frame that fails either check
    produces a refusal reply and no process.
    """
    request_id = ""
    try:
        payload = read_frame(connection.read_exact)
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
        reply = serve_one(request, secret=secret, runner=runner)
        connection.write_all(encode_frame(reply.to_frame()))
        return "served" if reply.status == "ok" else "refused"
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


def serve_pipe(*, device_id: str, secret: bytes, listener: Listener | None = None,
               runner: Runner = run_process, max_requests: int | None = None,
               should_stop: Callable[[], bool] | None = None) -> ServeStats:
    """Accept and serve requests until stopped.

    ``max_requests`` and ``should_stop`` exist so a test can run the real loop
    over a fake listener, and so the shipped helper can be asked to stop without
    being killed. Neither changes how a request is served.
    """
    if not isinstance(secret, (bytes, bytearray)) or not secret:
        raise UserHelperError(USER_HELPER_REFUSED, "the helper has no deployment secret")
    own_listener = listener is None
    active = listener or WindowsPipeListener(device_id)
    guard = ReplayGuard()
    stats = ServeStats()
    try:
        while True:
            if should_stop is not None and should_stop():
                break
            if max_requests is not None and stats.served + stats.refused >= max_requests:
                break
            try:
                connection = active.accept(ACCEPT_POLL_SECONDS)
            except UserHelperError as refused:
                stats.last_error = refused.code
                break
            if connection is None:
                continue
            outcome = handle_connection(connection, secret=bytes(secret),
                                        guard=guard, runner=runner)
            if outcome == "served":
                stats.served += 1
            else:
                stats.refused += 1
    finally:
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
        print(f"refused:{refused.code}", file=sys.stderr)
        return 2
    print(f"served={stats.served} refused={stats.refused}")
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
