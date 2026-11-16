"""#7841 — why the last result append ended the way it did.

The append functions in ``history.py`` keep their boolean contract and every
write unchanged; this module only names the branch that decided it, so a
refusal can be read from the log instead of re-derived.

A reason lives in a context variable: a concurrent request served by the same
store object can never overwrite another turn's reason. Only one known word is
ever kept, the words carry no id, body or path, and recording a reason never
raises and never writes.
"""
from __future__ import annotations

import contextvars

APPEND_REASON_STORED = "stored"
APPEND_REASON_ALREADY_COMPLETED = "already_completed"
APPEND_REASON_SAME_MESSAGE = "same_message"
APPEND_REASON_SUMMARY_SAME = "summary_same"
APPEND_REASON_SUMMARY_GUARD = "summary_guard"

_APPEND_REASON_CODES = frozenset({
    APPEND_REASON_STORED,
    APPEND_REASON_ALREADY_COMPLETED,
    APPEND_REASON_SAME_MESSAGE,
    APPEND_REASON_SUMMARY_SAME,
    APPEND_REASON_SUMMARY_GUARD,
})
_APPEND_REASON = contextvars.ContextVar("chat_append_reason", default="none")


def note_append_reason(code: str) -> None:
    """Record the reason the current append ended; never raises, never writes."""

    _APPEND_REASON.set(code if code in _APPEND_REASON_CODES else "other")


def last_append_reason() -> str:
    """The reason the most recent append in this context recorded."""

    return _APPEND_REASON.get()


def refused(code: str) -> bool:
    """Record the guard that refused this append, then answer ``False``."""

    note_append_reason(code)
    return False


def stored() -> bool:
    """Record that this append landed, then answer ``True``."""

    note_append_reason(APPEND_REASON_STORED)
    return True
