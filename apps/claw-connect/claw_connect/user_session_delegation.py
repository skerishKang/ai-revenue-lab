"""#7065 (c) stage 2 — the SYSTEM agent's side of the user-session delegation.

The Connector's agent runs as ``LocalSystem``. When a request asks to run as the
logged-in user, the agent does not run it: it forwards the request over the local
pipe to the user's helper and returns what the helper observed.

The rule that matters most here is the failure rule. When the helper is absent
the user is logged out, and that is reported as ``user_session_unavailable``.
The agent never falls back to running the command as SYSTEM: a silent SYSTEM
answer is exactly the behaviour #7065 exists to remove, and it would make a
logged-out PC look healthy while every answer came from the wrong account.

Framing is shared with :mod:`claw_connect.user_helper_service` — a 4-byte
big-endian length then UTF-8 JSON — so the two sides cannot drift apart.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

from .user_helper_service import Connection, encode_frame, read_frame
from .user_session_helper import (
    HelperReply,
    HelperRequest,
    USER_HELPER_BAD_REPLY,
    USER_HELPER_TIMEOUT,
    USER_SESSION_UNAVAILABLE,
    UserHelperError,
    decode_reply,
    pipe_path,
    request_nonce,
)

#: How long the agent waits for the helper to answer, on top of the request's own
#: timeout. The helper bounds the child; this bounds the pipe, so a helper that
#: died mid-request cannot hold the agent.
REPLY_GRACE_SECONDS = 5


@dataclass(frozen=True, slots=True)
class DelegationOutcome:
    """What one delegation produced, and which lane produced it.

    ``lane`` is always ``"user"`` on success. It is never ``"system"``: this
    module has no SYSTEM fallback, and a value that claimed one would be a lie.
    """

    reply: HelperReply
    lane: str = "user"
    duration_ms: int = 0


def open_pipe_connection(path: str) -> Connection:
    """Open the helper's pipe as a client.

    Windows only, and only the one pipe name the helper owns. A missing pipe is
    the logged-out case and is translated by the caller, not here.
    """
    import ctypes  # noqa: PLC0415 - platform gate
    import sys  # noqa: PLC0415

    if sys.platform != "win32":
        raise FileNotFoundError(path)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.WaitNamedPipeW(ctypes.c_wchar_p(path), 2000)
    handle = kernel.CreateFileW(
        ctypes.c_wchar_p(path),
        0x80000000 | 0x40000000,  # GENERIC_READ | GENERIC_WRITE
        0, None, 3, 0, None,      # OPEN_EXISTING
    )
    if handle == ctypes.c_void_p(-1).value or not handle:
        raise FileNotFoundError(path)
    from .user_helper_service import WindowsPipeConnection  # noqa: PLC0415

    return WindowsPipeConnection(handle)


def delegate_to_user(*, request: HelperRequest, secret: bytes, device_id: str,
                     connect: Callable[[str], Connection] | None = None
                     ) -> DelegationOutcome:
    """Forward one request to the logged-in user's helper.

    Raises :class:`UserHelperError` with ``user_session_unavailable`` when the
    helper is not there. That is a real outcome, not an error to paper over: the
    caller reports it and stops.
    """
    started = time.monotonic()
    path = pipe_path(device_id)
    opener = connect or open_pipe_connection
    try:
        connection = opener(path)
    except FileNotFoundError as absent:
        raise UserHelperError(
            USER_SESSION_UNAVAILABLE,
            "no helper is listening; the user is not logged in",
        ) from absent
    except OSError as unavailable:
        raise UserHelperError(
            USER_SESSION_UNAVAILABLE,
            "the helper pipe could not be opened",
        ) from unavailable

    try:
        frame = encode_frame({
            "request_id": request.request_id,
            "nonce": request_nonce(secret, request),
            "shell": request.shell,
            "cwd": request.cwd,
            "command": request.command,
            "timeout_seconds": request.timeout_seconds,
            "distro": request.distro,
        })
        connection.write_all(frame)
        payload = read_frame(connection.read_exact)
    except UserHelperError:
        raise
    except Exception as broken:
        # A pipe that breaks mid-exchange is a helper that went away. It is not
        # a command result, and it must not be reported as one.
        raise UserHelperError(
            USER_SESSION_UNAVAILABLE,
            "the helper connection ended before it answered",
        ) from broken
    finally:
        connection.close()

    reply = decode_reply(_frame_bytes(payload))
    if reply.request_id != request.request_id:
        raise UserHelperError(
            USER_HELPER_BAD_REPLY,
            "the reply answers a different request",
        )
    return DelegationOutcome(
        reply=reply,
        lane="user",
        duration_ms=int((time.monotonic() - started) * 1000),
    )


def _frame_bytes(payload: dict[str, Any]) -> bytes:
    """Re-encode a decoded frame so the stage-1 decoder stays the only reader.

    The stage-1 ``decode_reply`` is the single place that decides what a reply
    body means, including that a non-UTF-8 body is refused. Routing through it
    keeps one definition of "readable reply" instead of two.
    """
    import json  # noqa: PLC0415

    return json.dumps(payload, ensure_ascii=True).encode("utf-8")


def run_as_user(*, request: HelperRequest, secret: bytes, device_id: str,
                connect: Callable[[str], Connection] | None = None
                ) -> DelegationOutcome:
    """The agent's entry point for a run-as-user request.

    This is the whole contract in one place: try the user lane, and if the user
    is not there, say so. There is deliberately no second attempt on any other
    lane.
    """
    return delegate_to_user(request=request, secret=secret, device_id=device_id,
                            connect=connect)
