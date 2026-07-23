"""SQLite connection and migration runner.

Independent from sibling apps. Applies SQL migration files from the
migrations/ directory in sorted order, tracking applied versions in
schema_migrations.

``get_connection`` returns the backend-neutral
:class:`~app.database.sqlite.SQLiteConnection` adapter so repository and service
code never touches ``sqlite3`` directly. The SQLite migration runner below
operates on the underlying raw connection (``conn.raw``) because it relies on
SQLite-specific behaviour (``PRAGMA``, ``sqlite3.complete_statement``).
"""

import os
import sqlite3
from pathlib import Path

from app.database.sqlite import SQLiteConnection


class MigrationError(RuntimeError):
    def __init__(self, filename: str, original_error: Exception):
        self.filename = filename
        self.original_error = original_error
        super().__init__(f"migration {filename} failed: {original_error}")


def get_connection(db_path: str) -> SQLiteConnection:
    """Open a SQLite connection wrapped in the backend-neutral adapter.

    The returned :class:`SQLiteConnection` is transparent — it delegates every
    operation to the underlying ``sqlite3.Connection`` — but translates
    ``sqlite3.IntegrityError`` into the neutral
    :class:`~app.database.errors.IntegrityError` so callers stay
    backend-agnostic.
    """
    db_path = str(db_path)
    if db_path != ":memory:":
        parent = os.path.dirname(os.path.abspath(db_path))
        os.makedirs(parent, exist_ok=True)
    raw = sqlite3.connect(db_path, check_same_thread=False)
    raw.row_factory = sqlite3.Row
    raw.execute("PRAGMA foreign_keys = ON")
    return SQLiteConnection(raw)


def is_sql_trivia(value: str) -> bool:
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
        raise ValueError(f"incomplete SQL statement near: {remainder[:80]}")


def apply_migrations(
    conn,
    migrations_dir: str = "migrations",
) -> list[str]:
    # Operate on the underlying raw sqlite3 connection so the SQLite-specific
    # migration machinery (PRAGMA, complete_statement, sqlite3.Error) behaves
    # exactly as before whether *conn* is the adapter or a raw connection.
    conn = getattr(conn, "raw", conn)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (
                strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            )
        )
    """)
    conn.commit()

    applied = set()
    for row in conn.execute("SELECT version FROM schema_migrations"):
        applied.add(row["version"])

    migrations_path = Path(migrations_dir)
    files = sorted(migrations_path.glob("*.sql"))
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
            # Run FK check after each migration's statements
            violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise MigrationError(
                    filename,
                    RuntimeError(
                        f"foreign key violations after migration: {violations}"
                    ),
                )
            conn.execute(
                "INSERT INTO schema_migrations (version) VALUES (?)",
                (filename,),
            )
            conn.commit()
            applied_versions.append(filename)
        except MigrationError:
            # MigrationError raised above (e.g. FK violations) — rollback
            # and re-raise. Must catch before sqlite3.Error to ensure
            # the transaction is properly rolled back.
            if conn.in_transaction:
                conn.rollback()
            raise
        except sqlite3.Error as exc:
            conn.rollback()
            raise MigrationError(filename, exc) from exc

    return applied_versions
