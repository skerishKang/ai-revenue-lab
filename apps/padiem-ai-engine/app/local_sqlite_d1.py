"""D1-shaped SQLite binding for the CPython Engine host.

The Engine's durable lanes (``ENGINE_IDEMPOTENCY``, the tool result ledger) speak
the Cloudflare D1 surface: ``prepare(sql).bind(...).first()/all()/run()``. Chat
and the broker already run those lanes on a local SQLite file through the same
facade shape; this module is that facade for the Engine, and nothing else.

It creates no table and owns no schema: ``apply_engine_migrations`` applies the
reviewed ``apps/padiem-ai-engine/migrations`` set in filename order under its own
ledger, so a host file can never look migrated to wrangler and the migration set
stays the single source.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

LOCAL_ENGINE_LEDGER_TABLE = "padiem_local_engine_migration_ledger"
DEFAULT_ENGINE_MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


class LocalSqliteD1:
    """The ``ENGINE_IDEMPOTENCY`` surface over one SQLite connection."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        if connection is None:
            raise ValueError("a SQLite connection is required")
        self.connection = connection

    def prepare(self, sql: str) -> "LocalSqliteStatement":
        if not isinstance(sql, str) or not sql.strip():
            raise ValueError("D1 prepare requires statement text")
        return LocalSqliteStatement(self.connection, sql)

    async def batch(self, statements: Iterable["LocalSqliteStatement"]) -> list[dict[str, Any]]:
        """Run the statements as one atomic unit, like ``env.DB.batch()``."""

        prepared = list(statements)
        for statement in prepared:
            if not isinstance(statement, LocalSqliteStatement) or (
                statement.connection is not self.connection
            ):
                raise TypeError("batch accepts only statements prepared on this binding")
        results: list[dict[str, Any]] = []
        self.connection.execute("BEGIN")
        try:
            for statement in prepared:
                results.append(statement._run_result())
            self.connection.execute("COMMIT")
        except BaseException:
            try:
                self.connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        return results


class LocalSqliteStatement:
    """One prepared statement with D1's ``bind/first/all/run`` shape."""

    def __init__(self, connection: sqlite3.Connection, sql: str) -> None:
        self.connection = connection
        self.sql = sql
        self._params: tuple[Any, ...] = ()

    def bind(self, *params: Any) -> "LocalSqliteStatement":
        self._params = params
        return self

    def _rows(self) -> list[dict[str, Any]]:
        cursor = self.connection.execute(self.sql, self._params)
        try:
            return [dict(row) for row in cursor.fetchall()]
        finally:
            cursor.close()

    async def first(self) -> dict[str, Any] | None:
        rows = self._rows()
        return rows[0] if rows else None

    async def all(self) -> dict[str, Any]:
        rows = self._rows()
        return {"results": rows, "success": True, "meta": {"rows_read": len(rows)}}

    def _run_result(self) -> dict[str, Any]:
        cursor = self.connection.execute(self.sql, self._params)
        try:
            changes = cursor.rowcount if cursor.rowcount is not None else 0
        finally:
            cursor.close()
        return {"success": True, "meta": {"changes": changes}}

    async def run(self) -> dict[str, Any]:
        return self._run_result()


def connect_local_database(path: str | Path) -> sqlite3.Connection:
    """Open the host Engine database with the same stance as the Chat host."""

    connection = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def apply_engine_migrations(
    connection: sqlite3.Connection,
    migrations_dir: str | Path = DEFAULT_ENGINE_MIGRATIONS_DIR,
) -> int:
    """Apply every pending Engine migration in filename order; return the count."""

    directory = Path(migrations_dir)
    if not directory.is_dir():
        raise ValueError("engine migrations directory is missing")
    connection.execute(
        f"CREATE TABLE IF NOT EXISTS {LOCAL_ENGINE_LEDGER_TABLE} ("
        "name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    applied = {
        row[0]
        for row in connection.execute(f"SELECT name FROM {LOCAL_ENGINE_LEDGER_TABLE}")
    }
    count = 0
    for path in sorted(directory.glob("*.sql")):
        if path.name in applied:
            continue
        connection.executescript(path.read_text(encoding="utf-8"))
        connection.execute(
            f"INSERT INTO {LOCAL_ENGINE_LEDGER_TABLE} (name, applied_at) VALUES (?, ?)",
            (path.name, datetime.now(timezone.utc).isoformat()),
        )
        count += 1
    return count


def binding_from_database(
    connection: sqlite3.Connection,
) -> LocalSqliteD1:
    return LocalSqliteD1(connection)


__all__ = [
    "DEFAULT_ENGINE_MIGRATIONS_DIR",
    "LOCAL_ENGINE_LEDGER_TABLE",
    "LocalSqliteD1",
    "LocalSqliteStatement",
    "apply_engine_migrations",
    "binding_from_database",
    "connect_local_database",
]
