"""Load-bearing regression for SqliteD1.batch — the surface Chat stores write through.

The batch contract is what makes guarded conditional writes honest on SQLite:
a refused `UPDATE ... WHERE <guard> RETURNING` reports no row and `changes == 0`
(history.py:_batch_returned_row), and a later failing statement must undo the
earlier ones, because `env.DB.batch()` on D1 is atomic.
"""
from __future__ import annotations

import sqlite3

import pytest

from app.d1_sqlite import SqliteD1, connect


@pytest.fixture()
def db() -> SqliteD1:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("CREATE TABLE t (id TEXT PRIMARY KEY, status TEXT NOT NULL)")
    yield SqliteD1(connection)
    connection.close()


@pytest.mark.asyncio
async def test_batch_returns_per_statement_rows_and_changes(db: SqliteD1):
    winner_update = db.prepare(
        "UPDATE t SET status = ? WHERE id = ? AND status = ? RETURNING id"
    ).bind("done", "a", "open")
    losing_update = db.prepare(
        "UPDATE t SET status = ? WHERE id = ? AND status = ? RETURNING id"
    ).bind("done", "a", "open")
    await db.batch([db.prepare("INSERT INTO t (id, status) VALUES (?, ?)").bind("a", "open")])

    results = await db.batch([winner_update, losing_update])

    # The winner reports its own RETURNING row and one changed row; the loser —
    # same statement, guard already consumed — reports neither. That 0 is how a
    # losing concurrent writer refuses instead of inheriting the winner's row.
    assert results[0]["results"] == [{"id": "a"}]
    assert results[0]["meta"]["changes"] == 1
    assert results[0]["meta"]["rows_written"] == 1
    assert results[1]["results"] == []
    assert results[1]["meta"]["changes"] == 0


@pytest.mark.asyncio
async def test_batch_is_atomic_when_a_later_statement_fails(db: SqliteD1):
    with pytest.raises(sqlite3.IntegrityError):
        await db.batch([
            db.prepare("INSERT INTO t (id, status) VALUES (?, ?)").bind("a", "open"),
            db.prepare("INSERT INTO t (id, status) VALUES (?, ?)").bind("a", "again"),
        ])

    # The first insert must have been rolled back with the failing one; if
    # atomicity were ever restored per-statement, this read would find the row.
    assert await db.prepare("SELECT id FROM t WHERE id = ?").bind("a").first() is None


@pytest.mark.asyncio
async def test_batch_refuses_statements_from_another_binding(db: SqliteD1):
    foreign_connection = sqlite3.connect(":memory:")
    foreign = SqliteD1(foreign_connection)
    with pytest.raises(TypeError):
        await db.batch([foreign.prepare("SELECT 1")])
    foreign_connection.close()


@pytest.mark.asyncio
async def test_run_reports_changes_for_guarded_writes():
    # The queue lane reads run().meta.changes through _changed_rows; connect()
    # (the mesh-queue door) must keep that shape and stay WAL/Row-configured.
    binding = connect(":memory:")
    try:
        binding.execute("CREATE TABLE g (id INTEGER PRIMARY KEY, v TEXT)")
        db = SqliteD1(binding)
        written = await db.prepare("INSERT INTO g (v) VALUES (?)").bind("x").run()
        assert written["meta"]["changes"] == 1
        assert written["meta"]["last_row_id"] == 1
        assert written["meta"]["rows_written"] == 1
        untouched = await db.prepare("UPDATE g SET v = ? WHERE id = ?").bind("y", 99).run()
        assert untouched["meta"]["changes"] == 0
    finally:
        binding.close()
