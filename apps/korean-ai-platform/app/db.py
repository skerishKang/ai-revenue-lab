"""Product-local SQLite connection and deterministic forward-only migrations.

This is an independent implementation inside the Korean AI Platform workspace
(Business 14). It does not import any sibling Business code. Only the standard
``sqlite3`` module is used; no ORM and no network database.

Design rules:
- importing this module never creates a DB file or opens a connection;
- connections are opened per call and always closed by the caller;
- no connection or cursor is kept as a module-global singleton;
- ``PRAGMA foreign_keys = ON`` and ``sqlite3.Row`` on every connection;
- migrations are deterministic, forward-only, idempotent, one transaction each;
- failures are normalized to fixed safe errors; raw SQL / paths / SQLite error
  strings are never surfaced to end users (original error kept as ``__cause__``).
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path


class PersistenceError(RuntimeError):
    """Fixed, safe persistence failure shown to users.

    The message is constant on purpose: it never leaks SQL, parameters, raw
    SQLite errors, or filesystem paths. The original exception, if any, is
    attached via ``__cause__`` for internal diagnostics only.
    """

    SAFE_MESSAGE = (
        "로컬 저장소에 변경사항을 기록하지 못했습니다. "
        "작업 상태는 변경되지 않았습니다."
    )

    def __init__(self, original: Exception | None = None):
        super().__init__(self.SAFE_MESSAGE)
        if original is not None:
            self.__cause__ = original


class MigrationError(RuntimeError):
    """A migration failed to apply. ``filename`` identifies which one."""

    def __init__(self, filename: str, original_error: Exception):
        self.filename = filename
        self.original_error = original_error
        super().__init__(f"migration {filename} failed")
        self.__cause__ = original_error


def get_connection(db_path: str) -> sqlite3.Connection:
    """Open a SQLite connection with safe defaults.

    Parent directories are created for file paths. ``:memory:`` is supported
    for tests. The connection uses ``sqlite3.Row``, enables foreign keys, and
    runs in autocommit mode (``isolation_level=None``) so callers control
    transactions explicitly with ``BEGIN``/``COMMIT``/``ROLLBACK``.
    """
    db_path = str(db_path)
    if db_path != ":memory:":
        parent = os.path.dirname(os.path.abspath(db_path))
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def is_sql_trivia(value: str) -> bool:
    """True if ``value`` is only whitespace and/or SQL comments."""
    i = 0
    while i < len(value):
        ch = value[i]
        if ch in (" ", "\t", "\n", "\r"):
            i += 1
        elif ch == "-" and i + 1 < len(value) and value[i + 1] == "-":
            i += 2
            while i < len(value) and value[i] not in ("\n", "\r"):
                i += 1
        elif ch == "/" and i + 1 < len(value) and value[i + 1] == "*":
            i += 2
            closed = False
            while i + 1 < len(value):
                if value[i] == "*" and value[i + 1] == "/":
                    closed = True
                    i += 2
                    break
                i += 1
            if not closed:
                return False
        else:
            return False
    return True


def iter_sql_statements(sql: str):
    """Yield complete SQL statements; reject incomplete trailing SQL."""
    buffer: list[str] = []
    for ch in sql:
        buffer.append(ch)
        if ch == ";":
            candidate = "".join(buffer)
            if sqlite3.complete_statement(candidate):
                stmt = candidate.strip()
                if stmt:
                    yield stmt
                buffer.clear()
    remainder = "".join(buffer)
    if remainder.strip() and not is_sql_trivia(remainder):
        raise ValueError("incomplete SQL statement")


def apply_migrations(
    conn: sqlite3.Connection,
    migrations_dir: str = "migrations",
) -> list[str]:
    """Apply pending ``*.sql`` migrations in deterministic filename order.

    Each migration runs in its own ``BEGIN IMMEDIATE`` transaction; on success
    its version is recorded and committed, on failure the transaction is rolled
    back and a :class:`MigrationError` is raised (stopping at the first
    failure). Already-applied migrations are skipped, so re-running is
    idempotent. Does not rely on ``executescript`` implicit transactions.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT (
                    strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                )
            )
            """
        )
        conn.execute("COMMIT")
    except sqlite3.Error as exc:
        conn.execute("ROLLBACK")
        raise MigrationError("schema_migrations", exc) from exc

    applied = {
        row["version"] for row in conn.execute("SELECT version FROM schema_migrations")
    }

    migrations_path = Path(migrations_dir)
    files = sorted(migrations_path.glob("*.sql"), key=lambda p: p.name)
    applied_versions: list[str] = []

    for f in files:
        filename = f.name
        if filename in applied:
            continue

        try:
            sql = f.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise MigrationError(filename, exc) from exc

        try:
            statements = list(iter_sql_statements(sql))
        except ValueError as exc:
            raise MigrationError(filename, exc) from exc

        try:
            conn.execute("BEGIN IMMEDIATE")
            for stmt in statements:
                conn.execute(stmt)
            conn.execute(
                "INSERT INTO schema_migrations (version) VALUES (?)",
                (filename,),
            )
            conn.execute("COMMIT")
            applied_versions.append(filename)
        except sqlite3.Error as exc:
            conn.execute("ROLLBACK")
            raise MigrationError(filename, exc) from exc

    return applied_versions
