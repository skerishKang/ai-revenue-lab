"""#7273 후속: itemize the bounded connector-grant check on one journal line.

The 3-second budget stays exactly as it is. This module only records where a
turn's check spent its time (product profile read, identity session refresh,
identity workspace resolve, both Google state round trips, the Engine grant
state read), so a timeout stops being a single opaque number. Timings live on
the request state for the life of one turn and never persist across turns.
"""

from __future__ import annotations

import time
from typing import Any

_TIMINGS_ATTR = "calendar_grant_timings"


def grant_timings(request: Any) -> dict[str, float]:
    """The per-request timing bucket, or ``{}`` when the request has no state."""

    state = getattr(request, "state", None)
    if state is None:
        return {}
    timings = getattr(state, _TIMINGS_ATTR, None)
    if not isinstance(timings, dict):
        timings = {}
        try:
            setattr(state, _TIMINGS_ATTR, timings)
        except Exception:  # noqa: BLE001 - timing is best-effort only
            return {}
    return timings


def record_ms(
    timings: dict[str, float] | None, key: str, started: float
) -> None:
    """Accumulate one segment's elapsed milliseconds under ``key``."""

    if not isinstance(timings, dict):
        return
    timings[key] = timings.get(key, 0.0) + (time.perf_counter() - started) * 1000.0


def format_field(timings: dict[str, float] | None, key: str) -> str:
    """One decimal field for the journal line; ``-`` when never measured."""

    if not isinstance(timings, dict):
        return "-"
    value = timings.get(key)
    return f"{value:.1f}" if isinstance(value, float) else "-"


__all__ = ["format_field", "grant_timings", "record_ms"]
