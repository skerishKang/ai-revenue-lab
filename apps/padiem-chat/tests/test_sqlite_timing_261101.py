"""The shared SQLite facade reports queue/lock wait separately from execution."""
from __future__ import annotations

import sqlite3
import threading

import pytest

from app import d1_sqlite
from app.request_timing import STAGES, reset_timing, start_timing


@pytest.mark.asyncio
@pytest.mark.parametrize("threaded", [False, True])
@pytest.mark.parametrize("fails", [False, True])
async def test_sqlite_timing_records_both_durations_even_when_execution_fails(monkeypatch, threaded, fails):
    conn = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False)
    db = d1_sqlite.SqliteD1(conn, threaded=threaded)
    timing, token = start_timing()
    timestamps = iter([1.0, 1.125, 1.175])
    monkeypatch.setattr(d1_sqlite, "perf_counter", lambda: next(timestamps))
    caller_thread = threading.get_ident()
    execution_threads = []

    def execute():
        execution_threads.append(threading.get_ident())
        if fails:
            raise sqlite3.OperationalError("synthetic private SQL/data must not be recorded")
        return "result"

    try:
        if fails:
            with pytest.raises(sqlite3.OperationalError):
                await db._invoke(execute)
        else:
            assert await db._invoke(execute) == "result"
        expected = dict.fromkeys(STAGES, 0.0)
        expected.update(sqlite_wait=125.0, sqlite_execute=50.0)
        assert timing.snapshot() == expected
        assert (execution_threads[0] != caller_thread) is threaded
    finally:
        reset_timing(token)
        conn.close()
