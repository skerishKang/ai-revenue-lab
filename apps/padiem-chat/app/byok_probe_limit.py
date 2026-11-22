"""Per-owner hourly budget for BYOK key verification calls.

The counter lives in the shared D1/SQLite database, so every worker enforces
the same budget. Only an owner id and fixed-window timestamps are stored — no
credential value is ever kept, logged, or returned to a caller.
"""
from __future__ import annotations

from time import time
from typing import Callable

PROBE_LIMIT_PER_HOUR = 10
PROBE_WINDOW_SECONDS = 3600


class ProbeRateLimited(Exception):
    def __init__(self, retry_after: int):
        super().__init__("byok_probe_rate_limited")
        self.retry_after = retry_after


class ProbeRateLimiter:
    def __init__(
        self,
        db,
        *,
        limit: int = PROBE_LIMIT_PER_HOUR,
        window_seconds: int = PROBE_WINDOW_SECONDS,
        clock: Callable[[], float] = time,
    ):
        if db is None:
            raise ValueError("a shared D1 binding is required")
        self.db = db
        self.limit = limit
        self.window_seconds = window_seconds
        self.clock = clock

    async def check_and_record(self, owner_id: str) -> None:
        now = self.clock()
        start = int(now // self.window_seconds) * self.window_seconds
        # Expired windows are retired in the same call; no separate sweeper.
        await self.db.prepare(
            "DELETE FROM byok_probe_windows WHERE window_start < ?"
        ).bind(start).run()
        row = await self.db.prepare(
            "INSERT INTO byok_probe_windows (user_id, window_start, count) "
            "VALUES (?, ?, 1) "
            "ON CONFLICT(user_id, window_start) DO UPDATE SET count = count + 1 "
            "WHERE count < ? RETURNING count"
        ).bind(owner_id, start, self.limit).first()
        if row is None:
            raise ProbeRateLimited(max(1, int(self.window_seconds - (now - start))))
