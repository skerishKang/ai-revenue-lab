"""#5881 follow-on — the D1 statement surface, backed by a local SQLite database.

Cloudflare hands `D1HistoryStore` a JS D1 binding: `prepare(sql).bind(*values)` and then
`await .run() / .first() / .all()`. The 컴2 PC queue runs the SAME store code against
this object, so claim, lease, nonce and consumption rules are not re-implemented in a
second place — the SQL and the guards stay the single authority they already are.

Only the three methods the stores actually call are provided, and `meta.changes` comes
from `SELECT CHANGES()` on the same connection because `_changed_rows` treats `0` as
"this conditional write matched nothing", which is how a losing concurrent writer never
inherits another writer's row (history.py:_changed_rows).
"""
from __future__ import annotations

import sqlite3
from typing import Any

__all__ = ["SqliteD1", "connect"]


def connect(path: str) -> sqlite3.Connection:
    """Open the queue database the way the lane needs it: WAL, autocommit, Row access."""

    connection = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


class _Statement:
    def __init__(self, connection: sqlite3.Connection, sql: str):
        self._connection = connection
        self._sql = sql
        self._values: tuple[Any, ...] = ()

    def bind(self, *values: Any) -> "_Statement":
        self._values = values
        return self

    def _execute(self) -> list[dict[str, Any]]:
        cursor = self._connection.execute(self._sql, self._values)
        # A statement that produces rows has a description; the stores read those rows
        # back through run(), so a SELECT-shaped guard is answered, not swallowed.
        if cursor.description is None:
            return []
        return [dict(row) for row in cursor.fetchall()]

    async def run(self) -> dict[str, Any]:
        rows = self._execute()
        changes = self._connection.execute("SELECT CHANGES()").fetchone()[0]
        return {"success": True, "meta": {"changes": changes, "last_row_id": 0},
                "results": rows}

    async def first(self) -> dict[str, Any] | None:
        rows = self._execute()
        return rows[0] if rows else None

    async def all(self) -> list[dict[str, Any]]:
        return self._execute()


class SqliteD1:
    """The `env.PADIEM_CHAT_DB` surface over one SQLite connection."""

    def __init__(self, connection: sqlite3.Connection):
        if connection is None:
            raise ValueError("a SQLite connection is required")
        self.connection = connection

    def prepare(self, sql: str) -> _Statement:
        if not isinstance(sql, str) or not sql.strip():
            raise ValueError("D1 prepare requires statement text")
        return _Statement(self.connection, sql)
