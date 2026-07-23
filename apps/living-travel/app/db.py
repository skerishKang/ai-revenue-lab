"""SQLite connection factory and migration engine."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Generator

from app.config import get_settings

_MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


class MigrationError(Exception):
    def __init__(self, filename: str, original: Exception) -> None:
        self.filename = filename
        self.original = original
        super().__init__(f"Migration {filename} failed: {original}")


def _iter_sql_statements(sql_text: str) -> Generator[str, None, None]:
    """Yield individual SQL statements, handling semicolons in values and block comments."""
    buf: list[str] = []
    in_block_comment = False
    i = 0
    text = sql_text
    length = len(text)

    while i < length:
        chunk = text[i : i + 2]
        if in_block_comment:
            if chunk == "*/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue
        if chunk == "/*":
            in_block_comment = True
            i += 2
            continue
        if chunk == "--":
            while i < length and text[i] != "\n":
                i += 1
            continue
        if text[i] == ";":
            stmt = "".join(buf).strip()
            if stmt:
                yield stmt
            buf = []
            i += 1
            continue
        buf.append(text[i])
        i += 1

    last = "".join(buf).strip()
    if last:
        yield last


def _apply_one(conn: sqlite3.Connection, filename: str, sql_text: str) -> None:
    for stmt in _iter_sql_statements(sql_text):
        conn.execute(stmt)
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, filename) VALUES (?, ?)",
        (filename, filename),
    )
    conn.commit()


def apply_migrations(db_path: str | None = None) -> None:
    if get_settings().database_backend == "postgresql":
        from app.database.postgres import apply_pg_migrations

        return apply_pg_migrations()
    if db_path is None:
        db_path = get_settings().database_url
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )
        conn.commit()

        applied = {
            row[0]
            for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
        }
        migration_files = sorted(_MIGRATIONS_DIR.glob("*.sql"))
        for mf in migration_files:
            if mf.name not in applied:
                sql_text = mf.read_text(encoding="utf-8")
                try:
                    _apply_one(conn, mf.name, sql_text)
                except Exception as exc:
                    conn.rollback()
                    raise MigrationError(mf.name, exc) from exc
    finally:
        conn.close()


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    if get_settings().database_backend == "postgresql" and db_path is None:
        from app.database.postgres import get_pg_connection

        return get_pg_connection()  # type: ignore[return-value]
    if db_path is None:
        db_path = get_settings().database_url
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn
