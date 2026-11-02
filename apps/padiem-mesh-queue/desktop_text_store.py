"""#6460 step 2 — one-shot typed text that never rests in the dispatch row.

The desktop lane's audit row carries the operation, never what was typed. The
value itself travels once: the Chat side deposits it under an unguessable
reference, the row names only the reference plus a length and a digest prefix,
and the executor takes it exactly once when it claims that dispatch. A taken or
expired value is gone — a second take answers None, and the executor then
refuses rather than typing a stale or guessed string.

In-memory by design: this store holds values that must not be written to the
queue database, a log, or a conversation. The process that holds it is the one
the executor claims from, and its lifetime is the dispatch's own minute.
"""
from __future__ import annotations

import hashlib
import re
import threading
import time

DEFAULT_TTL_SECONDS = 300
#: One typed value, bounded. The executor's own transport is line-oriented and
#: the relay sends one unicode pair per character, so a huge value is a stall,
#: not a feature.
MAX_TEXT_CHARS = 20000
_REF = re.compile(r"\A[0-9a-f]{32}\Z")


class DesktopTextStoreError(ValueError):
    """Bounded refusal of a deposit or take. Never carries the value."""


class DesktopTextStore:
    """Deposit once, take once. Thread-safe; every failure is fail-closed."""

    def __init__(self, *, ttl_seconds: int = DEFAULT_TTL_SECONDS,
                 max_chars: int = MAX_TEXT_CHARS) -> None:
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 900:
            raise DesktopTextStoreError("ttl is out of bounds")
        if type(max_chars) is not int or not 1 <= max_chars <= MAX_TEXT_CHARS:
            raise DesktopTextStoreError("text size is out of bounds")
        self._ttl = ttl_seconds
        self._max = max_chars
        self._entries: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()

    def _fresh(self, now: float) -> None:
        expired = [ref for ref, (deadline, _text) in self._entries.items()
                   if deadline <= now]
        for ref in expired:
            self._entries.pop(ref, None)

    async def deposit_desktop_text(self, *, ref: object, text: object) -> bool:
        if not isinstance(ref, str) or _REF.fullmatch(ref) is None:
            raise DesktopTextStoreError("reference is malformed")
        if not isinstance(text, str) or not text:
            raise DesktopTextStoreError("text is required")
        if len(text) > self._max:
            raise DesktopTextStoreError("text is out of bounds")
        if any(ord(ch) == 0 or ord(ch) == 13 for ch in text):
            raise DesktopTextStoreError("text carries a reserved character")
        now = time.monotonic()
        with self._lock:
            self._fresh(now)
            self._entries[ref] = (now + self._ttl, text)
        return True

    async def take_desktop_text(self, *, ref: object) -> str | None:
        if not isinstance(ref, str) or _REF.fullmatch(ref) is None:
            return None
        now = time.monotonic()
        with self._lock:
            self._fresh(now)
            entry = self._entries.pop(ref, None)
        if entry is None or entry[0] <= now:
            return None
        return entry[1]


def text_marker(text: str) -> str:
    """What the audit row may say about one typed value.

    Length and the first eight hex digits of its SHA-256: enough to tell two
    sends apart in an audit, useless for recovering the text.
    """
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
    return "%d:%s" % (len(text), digest)


__all__ = [
    "DesktopTextStore", "DesktopTextStoreError", "MAX_TEXT_CHARS",
    "text_marker",
]
