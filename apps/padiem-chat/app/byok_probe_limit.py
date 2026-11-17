"""Per-owner hourly budget for BYOK key verification calls.

Only an owner id and fixed-window timestamps are kept. No credential value is
ever stored here, logged, or returned to a caller.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic
from typing import Callable

PROBE_LIMIT_PER_HOUR = 10
PROBE_WINDOW_SECONDS = 3600


class ProbeRateLimited(Exception):
    def __init__(self, retry_after: int):
        super().__init__("byok_probe_rate_limited")
        self.retry_after = retry_after


@dataclass
class ProbeRateLimiter:
    limit: int = PROBE_LIMIT_PER_HOUR
    window_seconds: int = PROBE_WINDOW_SECONDS
    clock: Callable[[], float] = field(default=monotonic, repr=False)
    _windows: dict[str, tuple[float, int]] = field(default_factory=dict, repr=False)

    def check_and_record(self, owner_id: str) -> None:
        now = self.clock()
        start, count = self._windows.get(owner_id, (now, 0))
        if now - start >= self.window_seconds:
            start, count = now, 0
        if count >= self.limit:
            self._windows[owner_id] = (start, count)
            raise ProbeRateLimited(max(1, int(self.window_seconds - (now - start))))
        self._windows[owner_id] = (start, count + 1)
