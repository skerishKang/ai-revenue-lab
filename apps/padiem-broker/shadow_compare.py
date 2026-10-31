"""Opt-in, read-only broker shadow comparison. Never logs payloads or responses."""
from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Awaitable, Callable
from typing import Any

# Only methods audited as read-only.
READ_ONLY_METHODS = frozenset({"device_truth", "device_directory"})
DEFAULT_MAX_IN_FLIGHT = 32


class ShadowRecorder:
    """Append coarse outcomes only; no request, response or identifiers."""

    def __init__(self, path: str):
        self.path = path

    def record(self, method: str, outcome: str) -> None:
        line = json.dumps({"at": int(time.time()), "method": method, "outcome": outcome},
                          separators=(",", ":")).encode("utf-8") + b"\n"
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(self.path, flags, 0o600)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)


class ShadowDispatcher:
    """Bound per-process background work; skipped is an in-memory counter.

    Instantiate once per ASGI worker and expose skipped through the caller's
    monitoring when wired. Shutdown must await drain before closing transports.
    """

    def __init__(self, max_in_flight: int = DEFAULT_MAX_IN_FLIGHT):
        if max_in_flight < 1:
            raise ValueError("max_in_flight must be positive")
        self.max_in_flight = max_in_flight
        self.skipped = 0
        self._tasks: set[asyncio.Task[None]] = set()

    def submit(self, method, encoded, primary_result, shadow, recorder, timeout_seconds):
        if len(self._tasks) >= self.max_in_flight:
            self.skipped += 1
            return
        task = asyncio.create_task(
            self._compare(method, encoded, primary_result, shadow, recorder, timeout_seconds)
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _compare(self, method, encoded, primary_result, shadow, recorder, timeout_seconds):
        outcome = "shadow_error"
        try:
            secondary = await asyncio.wait_for(shadow(method, json.loads(encoded)), timeout_seconds)
            outcome = "match" if primary_result == secondary else "mismatch"
        except Exception:
            pass
        try:
            # Filesystem calls must not block the ASGI event loop.
            await asyncio.to_thread(recorder.record, method, outcome)
        except Exception:
            pass

    async def drain(self):
        """Wait for admitted comparisons before closing their client or loop."""
        while self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
            self._tasks.difference_update(task for task in tuple(self._tasks) if task.done())


_default_dispatcher = ShadowDispatcher()


async def compare_read(
    method: str,
    payload: dict[str, Any],
    *,
    primary: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]],
    shadow: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]],
    recorder: ShadowRecorder,
    timeout_seconds: float = 2.0,
    dispatcher: ShadowDispatcher | None = None,
) -> dict[str, Any]:
    """Return the primary response without waiting for comparison or recording."""
    if method not in READ_ONLY_METHODS or not isinstance(payload, dict):
        raise ValueError("unsupported read-only shadow request")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    primary_result = await primary(method, json.loads(encoded))
    (dispatcher or _default_dispatcher).submit(
        method, encoded, primary_result, shadow, recorder, timeout_seconds
    )
    return primary_result
