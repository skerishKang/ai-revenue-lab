"""One PRAGMA policy for every SQLite connection, and a WAL that shrinks when idle.

The COM2 deployment measured 200-600 ms per fsync (2026-11-03), so a commit in
``synchronous=FULL`` cost one to three of those while ``sqlite_wait`` stayed
under 1 ms — the cost sat in the file sync, not in the query. These tests pin
the policy at the places this process opens a connection, and pin that the idle
checkpoint actually truncates the WAL.
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
from time import perf_counter

import pytest

from app import sqlite_settings
from app.d1_sqlite import SqliteD1, connect

from app.sqlite_settings import (  # noqa: F401  (re-exported for the assertions below)
    AUTOCHECKPOINT_PAGES,
    BUSY_TIMEOUT_MS,
    CACHE_KIB,
    IDLE_CHECKPOINT_SECONDS,
)


def test_writer_connection_takes_the_deployment_policy(tmp_path):
    connection = connect(str(tmp_path / "chat.sqlite3"))
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        # 1 == NORMAL: WAL writes are not fsynced on every commit.
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 1
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == BUSY_TIMEOUT_MS
        assert connection.execute("PRAGMA cache_size").fetchone()[0] == CACHE_KIB
        assert connection.execute("PRAGMA wal_autocheckpoint").fetchone()[0] == AUTOCHECKPOINT_PAGES
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        connection.close()


def test_policy_constants_stay_inside_the_decided_bounds():
    # NORMAL is the decided trade; OFF would drop durability beyond that.
    assert sqlite_settings.BUSY_TIMEOUT_MS >= 1000
    assert sqlite_settings.AUTOCHECKPOINT_PAGES <= 1000
    assert sqlite_settings.READER_IDLE_SECONDS <= 120
    assert sqlite_settings.IDLE_CHECKPOINT_SECONDS >= 60


@pytest.mark.asyncio
async def test_reader_connection_can_never_write_and_waits_like_the_writer(tmp_path):
    db = _database(tmp_path)
    try:
        await db.prepare("SELECT value FROM sample").all()
        reader = db._reader_connections[0]
        assert reader.execute("PRAGMA query_only").fetchone()[0] == 1
        assert reader.execute("PRAGMA busy_timeout").fetchone()[0] == BUSY_TIMEOUT_MS
        with pytest.raises(sqlite3.OperationalError):
            reader.execute("INSERT INTO sample VALUES (9, 9)")
    finally:
        await db.close_readers()
        db.connection.close()


@pytest.mark.asyncio
async def test_idle_checkpoint_truncates_the_wal(tmp_path):
    db = _database(tmp_path)
    try:
        db.connection.execute("PRAGMA wal_autocheckpoint = 0")
        for value in range(1, 200):
            await db.prepare("INSERT INTO sample VALUES (?, ?)").bind(value + 1, value).run()
        wal = str(tmp_path / "chat.sqlite3") + "-wal"
        assert os.path.getsize(wal) > 0
        # Pretend the last statement was long enough ago to be "idle", and
        # that no checkpoint ran before: -inf is the "never" sentinel (0.0
        # reads as "just checked" on a freshly booted runner).
        db._last_statement = perf_counter() - 3600
        db._last_checkpoint = float("-inf")
        report = await db.checkpoint_if_idle()
        assert report.get("busy") == 0
        # The behavioural claim: the WAL file is gone (a fresh one starts at
        # frame 0 on the next write), not that this run copied N frames — an
        # autocheckpoint may already have copied them.
        assert os.path.getsize(wal) == 0
        assert "skipped" not in report
        # The facade keeps serving reads after the truncate.
        assert await db.prepare("SELECT COUNT(*) AS n FROM sample").first() == {"n": 200}
    finally:
        await db.close_readers()
        db.connection.close()


@pytest.mark.asyncio
async def test_checkpoint_is_skipped_while_traffic_is_recent(tmp_path):
    db = _database(tmp_path)
    try:
        await db.prepare("INSERT INTO sample VALUES (2, 20)").run()
        wal = str(tmp_path / "chat.sqlite3") + "-wal"
        before = os.path.getsize(wal)
        report = await db.checkpoint_if_idle()
        assert report == {"skipped": "recent_activity"}
        assert os.path.getsize(wal) == before
        assert await db.prepare("SELECT value FROM sample WHERE id=2").first() == {"value": 20}
    finally:
        await db.close_readers()
        db.connection.close()


@pytest.mark.asyncio
async def test_checkpoint_respects_the_interval_between_runs(tmp_path):
    db = _database(tmp_path)
    try:
        # Seed the interval clock explicitly: the first checkpoint must see an
        # interval that already elapsed, whatever the runner's uptime is.
        db._last_statement = perf_counter() - 3600
        db._last_checkpoint = perf_counter() - (2 * IDLE_CHECKPOINT_SECONDS)
        first = await db.checkpoint_if_idle()
        assert "skipped" not in first
        db._last_statement = perf_counter() - 3600
        second = await db.checkpoint_if_idle()
        assert second == {"skipped": "checked_recently"}
    finally:
        await db.close_readers()
        db.connection.close()


@pytest.mark.asyncio
async def test_first_checkpoint_is_allowed_on_a_freshly_booted_runner(tmp_path, monkeypatch):
    """Pins the CI flake: a runner that booted seconds ago has perf_counter
    near zero, and the old 0.0 'never checkpointed' sentinel read as
    'checked recently' (assert None == 0 / checked_recently flakes). With the
    -inf sentinel the first idle checkpoint runs at any epoch."""
    from app import d1_sqlite as d1_module

    db = _database(tmp_path)
    try:
        monkeypatch.setattr(d1_module, "perf_counter", lambda: 5.0)
        db.connection.execute("PRAGMA wal_autocheckpoint = 0")
        db._last_statement = 5.0 - 3600.0
        report = await db.checkpoint_if_idle()
        assert "skipped" not in report
        assert report.get("busy") == 0
    finally:
        await db.close_readers()
        db.connection.close()


def _database(tmp_path):
    connection = connect(str(tmp_path / "chat.sqlite3"))
    connection.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY, value INTEGER NOT NULL)")
    connection.execute("INSERT INTO sample VALUES (1, 10)")
    return SqliteD1(connection, threaded=True, read_workers=1)
