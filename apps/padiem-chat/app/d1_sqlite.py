"""#5881 follow-on — the D1 statement surface, backed by a local SQLite database.

Cloudflare hands `D1HistoryStore` a JS D1 binding: `prepare(sql).bind(*values)` and then
`await .run() / .first() / .all()`. The 컴2 PC queue runs the SAME store code against
this object, so claim, lease, nonce and consumption rules are not re-implemented in a
second place — the SQL and the guards stay the single authority they already are.

Only the methods the stores actually call are provided — `run`, `first`, `all`
for the queue lane and `batch` for the Chat stores that write through
`env.DB.batch()` — and `meta.changes` comes from `SELECT CHANGES()` on the same
connection because `_changed_rows` treats `0` as "this conditional write matched
nothing", which is how a losing concurrent writer never inherits another
writer's row (history.py:_changed_rows).
"""
from __future__ import annotations

import asyncio
import sqlite3
import threading
from time import perf_counter
from typing import Any

from .request_timing import record_duration

__all__ = ["SqliteD1", "connect"]


def connect(path: str) -> sqlite3.Connection:
    """Open the queue database the way the lane needs it: WAL, autocommit, Row access."""

    connection = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


class _InlineOwner:
    async def _invoke(self, function):
        return function()


class _Statement:
    def __init__(self, owner: "SqliteD1 | sqlite3.Connection", sql: str):
        # A bare connection is still accepted (older callers and tests build a statement
        # directly); it runs inline, without the binding's thread hop or lock.
        if isinstance(owner, sqlite3.Connection):
            self._owner = _InlineOwner()
            self._connection = owner
        else:
            self._owner = owner
            self._connection = owner.connection
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

    def _one_result(self) -> dict[str, Any]:
        rows = self._execute()
        # Positional access: a caller-supplied connection may not use Row access.
        changes, last_row_id = self._connection.execute(
            "SELECT CHANGES(), LAST_INSERT_ROWID()"
        ).fetchone()
        return {
            "success": True,
            "meta": {
                "changes": changes,
                "rows_written": changes,
                "last_row_id": last_row_id,
            },
            "results": rows,
        }

    async def run(self) -> dict[str, Any]:
        return await self._owner._invoke(self._one_result)

    async def first(self) -> dict[str, Any] | None:
        def first_row():
            rows = self._execute()
            return rows[0] if rows else None
        return await self._owner._invoke(first_row)

    async def all(self) -> list[dict[str, Any]]:
        return await self._owner._invoke(self._execute)


class SqliteD1:
    """The `env.PADIEM_CHAT_DB` surface over one SQLite connection."""

    def __init__(self, connection: sqlite3.Connection, *, threaded: bool = False):
        if connection is None:
            raise ValueError("a SQLite connection is required")
        self.connection = connection
        self._threaded = threaded
        self._lock = threading.RLock()

    async def _invoke(self, function):
        submitted = perf_counter()

        def locked():
            with self._lock:
                started = perf_counter()
                # Includes executor scheduling and writer-lock contention.
                # Only aggregate durations leave this facade; never SQL/data.
                record_duration("sqlite_wait", (started - submitted) * 1000)
                try:
                    return function()
                finally:
                    record_duration("sqlite_execute", (perf_counter() - started) * 1000)
        if self._threaded:
            return await asyncio.to_thread(locked)
        return locked()

    def prepare(self, sql: str) -> _Statement:
        if not isinstance(sql, str) or not sql.strip():
            raise ValueError("D1 prepare requires statement text")
        return _Statement(self, sql)

    async def batch(self, statements: list["_Statement"]) -> list[dict[str, Any]]:
        """Run the statements as ONE atomic unit, like `env.DB.batch()`.

        Every statement must come from this binding's own `prepare()`; a foreign
        object is refused rather than silently executed on another connection.
        Per-statement `meta` mirrors `run()`, so a guarded `RETURNING` write
        reads its own row count and a losing conditional writer still sees
        `changes == 0`.
        """

        prepared = list(statements)
        for statement in prepared:
            if not isinstance(statement, _Statement) or statement._connection is not self.connection:
                raise TypeError("batch accepts only statements prepared on this binding")
        return await self._invoke(lambda: self._batch_sync(prepared))

    def _batch_sync(self, prepared: list["_Statement"]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        # The connection is opened in autocommit mode, so the explicit
        # transaction is what makes the whole batch all-or-nothing.
        self.connection.execute("BEGIN")
        try:
            for statement in prepared:
                results.append(statement._one_result())
            self.connection.execute("COMMIT")
        except BaseException:
            # Not `Exception`: a call cancelled at this point raises CancelledError, which
            # is a BaseException. Leaking it past the rollback leaves the BEGIN open on the
            # one connection the whole process shares, and every later write then fails for
            # the life of that process. The rollback itself must not replace the reason the
            # caller is unwinding, so its own failure is swallowed after the original raise.
            try:
                self.connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        return results
