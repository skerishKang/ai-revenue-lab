"""Opt-in, read-only broker shadow comparison. Never logs payloads or responses."""
from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Awaitable, Callable
from typing import Any

# Only methods audited as read-only. Never accept material resolution, sessions
# or methods that can purge, rotate, create or otherwise mutate state.
READ_ONLY_METHODS = frozenset({"device_truth", "device_directory"})


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


async def compare_read(
    method: str,
    payload: dict[str, Any],
    *,
    primary: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]],
    shadow: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]],
    recorder: ShadowRecorder,
    timeout_seconds: float = 2.0,
) -> dict[str, Any]:
    """Return the primary result; shadow errors and log failures do not change it."""
    if method not in READ_ONLY_METHODS or not isinstance(payload, dict):
        raise ValueError("unsupported read-only shadow request")
    # Canonical copies isolate both calls and reject non-JSON values.
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    primary_result = await primary(method, json.loads(encoded))
    outcome = "shadow_error"
    try:
        secondary = await asyncio.wait_for(shadow(method, json.loads(encoded)), timeout_seconds)
        outcome = "match" if primary_result == secondary else "mismatch"
    except Exception:
        pass
    try:
        recorder.record(method, outcome)
    except OSError:
        pass
    return primary_result
