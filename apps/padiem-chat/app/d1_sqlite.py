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
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from pathlib import Path
import re
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
    async def _invoke(self, function, *, sql=None):
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

    def _execute(self, connection=None) -> list[dict[str, Any]]:
        cursor = (connection or self._connection).execute(self._sql, self._values)
        # A statement that produces rows has a description; the stores read those rows
        # back through run(), so a SELECT-shaped guard is answered, not swallowed.
        try:
            if cursor.description is None:
                return []
            return [dict(row) for row in cursor.fetchall()]
        finally:
            cursor.close()

    def _one_result(self, connection=None) -> dict[str, Any]:
        connection = connection or self._connection
        rows = self._execute(connection)
        # Positional access: a caller-supplied connection may not use Row access.
        changes, last_row_id = connection.execute(
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
        return await self._owner._invoke(self._one_result, sql=self._sql)

    async def first(self) -> dict[str, Any] | None:
        def first_row(connection=None):
            rows = self._execute(connection)
            return rows[0] if rows else None
        return await self._owner._invoke(first_row, sql=self._sql)

    async def all(self) -> list[dict[str, Any]]:
        return await self._owner._invoke(self._execute, sql=self._sql)


_SELECT = re.compile(r"\A\s*SELECT\b", re.IGNORECASE)
_CONNECTION_LOCAL = re.compile(
    r"\b(?:changes|total_changes|last_insert_rowid)\s*\(|\btemp\s*\.|\bsqlite_temp_(?:master|schema)\b",
    re.IGNORECASE,
)


def _independent_read(sql: str | None) -> bool:
    # first()/all() can execute UPDATE ... RETURNING. Route by conservative
    # SQL shape instead: WITH, PRAGMA, comments and unknown forms stay on the
    # writer, as do connection-local result/temporary-table queries.
    return isinstance(sql, str) and bool(_SELECT.match(sql)) and not _CONNECTION_LOCAL.search(sql)


class SqliteD1:
    """D1 surface with a serialized writer and optional independent WAL readers.

    The default keeps the existing single-connection contract. The CPython host
    may supply read_workers to reuse read-only connections on dedicated threads;
    every read gets a fresh committed snapshot, with no query/result cache.
    """

    def __init__(self, connection: sqlite3.Connection, *, threaded: bool = False, read_workers: int = 0):
        if connection is None:
            raise ValueError("a SQLite connection is required")
        if type(read_workers) is not int or read_workers < 0:
            raise ValueError("SQLite read_workers must be a non-negative integer")
        if read_workers and not threaded:
            raise ValueError("SQLite read workers require threaded mode")
        self.connection = connection
        self._threaded = threaded
        self._lock = threading.RLock()
        self._read_local = threading.local()
        self._reader_connections = []
        self._reader_lock = threading.Lock()
        self._read_executor = None
        self.read_workers = read_workers
        if read_workers:
            path = next((row[2] for row in connection.execute("PRAGMA database_list") if row[1] == "main"), "")
            if not path or connection.execute("PRAGMA journal_mode").fetchone()[0].lower() != "wal":
                raise ValueError("SQLite read workers require a file-backed WAL database")
            self._read_uri = Path(path).resolve().as_uri() + "?mode=ro&cache=private"
            self._read_executor = ThreadPoolExecutor(max_workers=read_workers, thread_name_prefix="chat-sqlite-read")

    def _read_connection(self):
        connection = getattr(self._read_local, "connection", None)
        if connection is None:
            connection = sqlite3.connect(self._read_uri, uri=True, isolation_level=None, check_same_thread=False)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            connection.execute("PRAGMA busy_timeout=5000")
            self._read_local.connection = connection
            with self._reader_lock:
                self._reader_connections.append(connection)
        return connection

    async def close_readers(self):
        """Drain this facade's readers; the caller still owns the writer."""
        executor, self._read_executor = self._read_executor, None
        if executor is None:
            return
        await asyncio.to_thread(executor.shutdown, wait=True)
        for connection in self._reader_connections:
            connection.close()
        self._reader_connections.clear()

    async def _invoke(self, function, *, sql=None):
        submitted = perf_counter()

        def timed(invoke):
            started = perf_counter()
            # Includes executor scheduling and writer-lock contention.
            # Only aggregate durations leave this facade; never SQL/data.
            record_duration("sqlite_wait", (started - submitted) * 1000)
            try:
                return invoke()
            finally:
                record_duration("sqlite_execute", (perf_counter() - started) * 1000)

        def locked():
            with self._lock:
                return timed(function)
        if self._read_executor is not None and _independent_read(sql):
            # A dedicated executor avoids filling the writer/default executor
            # with readers waiting for a pool slot. Each thread owns one RO
            # connection. Copy request context just as asyncio.to_thread does.
            context = copy_context()
            return await asyncio.get_running_loop().run_in_executor(
                self._read_executor, context.run, lambda: timed(lambda: function(self._read_connection())))
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
