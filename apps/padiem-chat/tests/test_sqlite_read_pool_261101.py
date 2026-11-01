"""WAL readers run independently; guarded mutations still use the writer."""
from __future__ import annotations

import asyncio
import sqlite3
import threading

import pytest

from app.d1_sqlite import SqliteD1, _independent_read, connect
from app.request_timing import reset_timing, start_timing


def database(tmp_path, *, readers=2):
    connection = connect(str(tmp_path / "chat.sqlite3"))
    connection.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY, value INTEGER NOT NULL)")
    connection.execute("INSERT INTO sample VALUES (1, 10)")
    return SqliteD1(connection, threaded=True, read_workers=readers)


@pytest.mark.asyncio
async def test_readers_see_committed_snapshot_without_waiting_for_writer(tmp_path):
    db = database(tmp_path)
    entered, release = threading.Event(), threading.Event()

    def held_write(value):
        entered.set()
        if not release.wait(5):
            raise RuntimeError("synthetic writer was not released")
        return value + 1

    db.connection.create_function("held_write", 1, held_write)
    writer = asyncio.create_task(db.prepare("UPDATE sample SET value=held_write(value) WHERE id=1").run())
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        # The writer cannot finish until the reads below return. Moving SELECT
        # back to the single writer lock makes this test fail at wait_for.
        rows = await asyncio.wait_for(asyncio.gather(*[
            db.prepare("SELECT value FROM sample WHERE id=?").bind(1).first() for _ in range(5)
        ]), timeout=1)
        assert rows == [{"value": 10}] * 5
        assert not writer.done()
        release.set()
        assert (await writer)["meta"]["changes"] == 1
        assert await db.prepare("SELECT value FROM sample WHERE id=1").first() == {"value": 11}
        assert 1 <= len(db._reader_connections) <= 2
    finally:
        release.set()
        await asyncio.gather(writer, return_exceptions=True)
        await db.close_readers()
        db.connection.close()


@pytest.mark.asyncio
async def test_returning_cte_and_batch_guards_keep_writer_semantics(tmp_path):
    db = database(tmp_path)
    try:
        assert await db.prepare("UPDATE sample SET value=value+1 WHERE id=1 RETURNING value").first() == {"value": 11}
        assert await db.prepare("SELECT changes() AS changed").first() == {"changed": 1}
        assert await db.prepare(
            "WITH target AS (SELECT 1 AS id) UPDATE sample SET value=value+1 "
            "WHERE id IN (SELECT id FROM target) RETURNING value"
        ).first() == {"value": 12}
        results = await db.batch([
            db.prepare("UPDATE sample SET value=13 WHERE id=1 AND value=12 RETURNING value"),
            db.prepare("SELECT changes() AS changed"),
            db.prepare("UPDATE sample SET value=14 WHERE id=1 AND value=12 RETURNING value"),
        ])
        assert results[0]["results"] == [{"value": 13}]
        assert results[0]["meta"]["changes"] == 1
        assert results[1]["results"] == [{"changed": 1}]
        assert results[2]["results"] == [] and results[2]["meta"]["changes"] == 0
        with pytest.raises(sqlite3.IntegrityError):
            await db.batch([
                db.prepare("INSERT INTO sample VALUES (2, 20)"),
                db.prepare("INSERT INTO sample VALUES (1, 99)"),
            ])
        assert await db.prepare("SELECT value FROM sample WHERE id=2").first() is None
        assert await db.prepare("DELETE FROM sample WHERE id=1 RETURNING value").first() == {"value": 13}
    finally:
        await db.close_readers()
        db.connection.close()


@pytest.mark.asyncio
async def test_concurrent_writers_preserve_exact_changed_row_counts(tmp_path):
    db = database(tmp_path)
    try:
        results = await asyncio.gather(*[
            db.prepare("UPDATE sample SET value=value+1 WHERE id=1 AND value=10").run()
            for _ in range(20)
        ])
        assert sorted(row["meta"]["changes"] for row in results) == [0] * 19 + [1]
        assert await db.prepare("SELECT value FROM sample").all() == [{"value": 11}]
    finally:
        await db.close_readers()
        db.connection.close()


@pytest.mark.asyncio
async def test_reader_connection_is_read_only_and_retains_request_timing(tmp_path):
    db = database(tmp_path)
    timing, token = start_timing()
    try:
        result = await db.prepare("SELECT value FROM sample").run()
        assert result["results"] == [{"value": 10}]
        assert result["meta"]["changes"] == 0
        stages = timing.snapshot()
        assert stages["sqlite_wait"] > 0 and stages["sqlite_execute"] > 0
        reader = db._reader_connections[0]
        assert reader.execute("PRAGMA query_only").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError):
            reader.execute("INSERT INTO sample VALUES (3, 30)")
        # Even disabling query_only cannot turn the mode=ro URI into a writer.
        reader.execute("PRAGMA query_only=OFF")
        with pytest.raises(sqlite3.OperationalError):
            reader.execute("INSERT INTO sample VALUES (3, 30)")
        assert db.connection.execute("SELECT COUNT(*) FROM sample").fetchone()[0] == 1
        await db.close_readers()
        await db.close_readers()
        assert db._reader_connections == []
        assert await db.prepare("SELECT value FROM sample").first() == {"value": 10}
    finally:
        reset_timing(token)
        await db.close_readers()
        db.connection.close()


@pytest.mark.parametrize("sql", [
    "UPDATE sample SET value=1 RETURNING value", "DELETE FROM sample RETURNING value",
    "WITH t AS (SELECT 1) SELECT * FROM t", "PRAGMA journal_mode", "SELECT changes()",
    "SELECT total_changes()", "SELECT last_insert_rowid()", "SELECT * FROM temp.sample",
    "SELECT * FROM sqlite_temp_master", "-- comment\nSELECT value FROM sample",
])
def test_unknown_or_connection_local_statements_stay_on_writer(sql):
    assert not _independent_read(sql)


def test_plain_select_is_eligible_and_pool_configuration_is_explicit():
    assert _independent_read("\nSELECT value FROM sample WHERE id=?")
    assert _independent_read("select count(*) from sample")
    conn = connect(":memory:")
    try:
        assert SqliteD1(conn, threaded=True)._read_executor is None
        for bad in (-1, True, 1.5):
            with pytest.raises(ValueError):
                SqliteD1(conn, threaded=True, read_workers=bad)
        with pytest.raises(ValueError, match="file-backed WAL"):
            SqliteD1(conn, threaded=True, read_workers=1)
        with pytest.raises(ValueError, match="threaded"):
            SqliteD1(conn, read_workers=1)
    finally:
        conn.close()
