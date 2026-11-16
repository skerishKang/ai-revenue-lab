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


def dispatch_silent_wait_seconds(
    expires_at: object, *, base_seconds: float, now: float | None = None,
) -> float:
    """The silent bound: ``min(configured, dispatch remaining)``.

    A dispatch with no usable deadline keeps the configured bound exactly
    (older servers stay compatible). An already-expired dispatch keeps it too:
    ``0`` means "wait forever" here, so it must never become the bound.
    """

    remaining = dispatch_remaining_seconds(expires_at, now=now)
    if base_seconds <= 0 or remaining is None or remaining <= 0:
        return base_seconds
    return min(base_seconds, remaining)


__all__ = [
    "SILENT_TIMEOUT_BODY",
    "SILENT_TIMEOUT_REASON",
    "dispatch_remaining_seconds",
    "dispatch_silent_wait_seconds",
]
