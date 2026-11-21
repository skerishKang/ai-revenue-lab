"""#7841 — tie the executor's silent wait to the dispatch it belongs to.

The poll response already names the dispatch's own ``expires_at``; a console
wait that outlives it can only end after the server has already given up on
the turn. These helpers keep that arithmetic out of the two giant executor
modules, whose file-size caps must not be raised.

Nothing here invents a new queue field: an older server that names no deadline
keeps the configured silent bound exactly as before.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

#: The reason a silent timeout carries in the result body. The server stores
#: and reads it like any other command output; no interpretation changes.
SILENT_TIMEOUT_REASON = "pc_console_silent"
SILENT_TIMEOUT_BODY = SILENT_TIMEOUT_REASON.encode("ascii")


def dispatch_remaining_seconds(expires_at: object, *, now: float | None = None) -> float | None:
    """Seconds left before the dispatch's own deadline, or None when absent."""

    if not isinstance(expires_at, str) or not expires_at.strip():
        return None
    text = expires_at.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp() - (time.time() if now is None else now)


#: #7994: an unresponsive PC ends within this many seconds of silence. The
#: bound is a silence budget, not a TTL: a dispatch whose lease outlives it must
#: not hold the worker that long, and a talking command restarts the clock on
#: every byte, so a slow-but-live console stays unlimited.
SILENT_END_SECONDS = 60.0


def dispatch_silent_wait_seconds(
    expires_at: object, *, base_seconds: float, now: float | None = None,
) -> float:
    """The silent bound: ``min(configured, 60 s)``, independent of the lease.

    A dispatch with no usable deadline keeps the configured bound capped at 60 s
    (#7994): the console wait is a silence budget, not a TTL, so an
    unresponsive PC ends quickly no matter how long its lease runs. An
    already-expired dispatch keeps the same 60 s — the silence, not the lease,
    decides when we stop waiting.
    """

    return min(float(base_seconds), SILENT_END_SECONDS)


__all__ = [
    "SILENT_TIMEOUT_BODY",
    "SILENT_TIMEOUT_REASON",
    "dispatch_remaining_seconds",
    "dispatch_silent_wait_seconds",
]
