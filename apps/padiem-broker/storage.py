"""Workers Durable Object SQLite-storage API over a plain sqlite3 connection.

The broker's durable code (#5573 Stage 2-C) talks to `ctx.storage`: `sql.exec()`
returning a cursor with `toArray()`/`rowsWritten`, and `transactionSync()`. This
adapter provides exactly that surface, so `LocalAgentBrokerDurableRuntime`, the
device HTTP service and every store composed from the same storage run on COM2
without their rules being re-written.

Serialization: one process (systemd) + `BEGIN IMMEDIATE`, the same stance the
mesh queue uses for its claim lane. `transactionSync` commits everything the
operation wrote or rolls the whole operation back — the DO's all-or-nothing
transaction, not a per-statement autocommit sequence.
"""
from __future__ import annotations

import sqlite3
import threading
from typing import Any, Callable, TypeVar

__all__ = ["SqLiteDurableStorage"]

_T = TypeVar("_T")


class _Cursor:
    def __init__(self, rows: list[dict[str, Any]], rows_written: int):
        self._rows = rows
        self.rowsWritten = rows_written

    def toArray(self) -> list[dict[str, Any]]:
        return list(self._rows)


class _Sql:
    def __init__(self, connection: sqlite3.Connection, lock):
        self._connection = connection
        self._lock = lock

    def exec(self, statement: str, *args: Any) -> _Cursor:
        with self._lock:
            cursor = self._connection.execute(statement, args)
            if cursor.description is not None:
                return _Cursor([dict(row) for row in cursor.fetchall()], 0)
            written = cursor.rowcount
            return _Cursor([], written if isinstance(written, int) and written > 0 else 0)


class SqLiteDurableStorage:
    """The `ctx.storage` surface the broker's durable code already consumes."""

    def __init__(self, connection: sqlite3.Connection):
        if connection is None:
            raise ValueError("a SQLite connection is required")
        if connection.row_factory is not sqlite3.Row:
            connection.row_factory = sqlite3.Row
        self._connection = connection
        self._lock = threading.RLock()
        self.sql = _Sql(connection, self._lock)

    @classmethod
    def open(cls, path: str, *, busy_timeout_ms: int = 5000) -> "SqLiteDurableStorage":
        connection = sqlite3.connect(
            path, isolation_level=None, check_same_thread=False
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
        return cls(connection)

    def transactionSync(self, operation: Callable[[], _T]) -> _T:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                result = operation()
                self._connection.execute("COMMIT")
            except BaseException:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise
            return result

    def close(self) -> None:
        with self._lock:
            self._connection.close()
