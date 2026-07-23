"""PostgreSQL backend: connection wrapper, placeholder translation, migrations.

Uses psycopg 3. The wrapper mimics the subset of the ``sqlite3.Connection``
interface used across Living Travel repositories so the same repository code
runs on both backends:

- ``execute(sql, params)`` with SQLite-style ``?`` placeholders
- dict-like rows (``row["col"]``)
- ``commit`` / ``rollback`` / ``close``
- ``with conn:`` commit-on-success / rollback-on-error (no close)

Migrations use a PostgreSQL advisory lock so concurrent Modal cold starts do
not race, and track applied files in ``schema_migrations`` (idempotent).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import get_settings

_PG_MIGRATIONS_DIR = (
    Path(__file__).resolve().parent.parent.parent / "migrations" / "postgresql"
)

# Fixed advisory-lock key guarding migration execution.
_MIGRATION_LOCK_ID = 723194301


class MigrationError(Exception):
    def __init__(self, filename: str, original: Exception) -> None:
        self.filename = filename
        self.original = original
        super().__init__(f"PostgreSQL migration {filename} failed: {original}")


def translate_placeholders(sql: str) -> str:
    """Convert SQLite ``?`` placeholders to psycopg ``%s``.

    Walks the SQL so placeholders inside string literals, quoted identifiers,
    and comments are left untouched, and escapes literal ``%`` to ``%%`` for
    psycopg's pyformat paramstyle.
    """
    out: list[str] = []
    i = 0
    n = len(sql)
    in_single = in_double = in_line = in_block = False

    def _emit(ch: str) -> None:
        # psycopg interprets '%' globally (pyformat), so literal '%' must be
        # doubled even inside string literals/identifiers/comments.
        out.append("%%" if ch == "%" else ch)

    while i < n:
        c = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""
        if in_line:
            _emit(c)
            if c == "\n":
                in_line = False
            i += 1
            continue
        if in_block:
            _emit(c)
            if c == "*" and nxt == "/":
                _emit(nxt)
                in_block = False
                i += 2
                continue
            i += 1
            continue
        if in_single:
            _emit(c)
            if c == "'":
                if nxt == "'":
                    _emit(nxt)
                    i += 2
                    continue
                in_single = False
            i += 1
            continue
        if in_double:
            _emit(c)
            if c == '"':
                in_double = False
            i += 1
            continue
        if c == "-" and nxt == "-":
            in_line = True
            _emit(c)
            i += 1
            continue
        if c == "/" and nxt == "*":
            in_block = True
            _emit(c)
            i += 1
            continue
        if c == "'":
            in_single = True
            _emit(c)
            i += 1
            continue
        if c == '"':
            in_double = True
            _emit(c)
            i += 1
            continue
        if c == "?":
            out.append("%s")
            i += 1
            continue
        _emit(c)
        i += 1
    return "".join(out)


class PostgresConnection:
    """Thin wrapper exposing the sqlite3-style interface over psycopg."""

    backend = "postgresql"

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    @property
    def raw(self) -> Any:
        return self._conn

    def execute(self, sql: str, params: Any = None) -> Any:
        translated = translate_placeholders(sql)
        if params is None:
            return self._conn.execute(translated)
        return self._conn.execute(translated, params)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "PostgresConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self._conn.commit()
        else:
            self._conn.rollback()
        return False


def _connect(conninfo: str) -> Any:
    import psycopg
    from psycopg.rows import dict_row

    return psycopg.connect(
        conninfo,
        row_factory=dict_row,
        autocommit=False,
        # Disable server-side prepared statements for Neon/pgbouncer pooling.
        prepare_threshold=None,
    )


def get_pg_connection() -> PostgresConnection:
    settings = get_settings()
    return PostgresConnection(_connect(settings.database_url))


def apply_pg_migrations(migration_url: str | None = None) -> None:
    """Apply PostgreSQL migrations idempotently under an advisory lock."""
    settings = get_settings()
    url = migration_url or settings.effective_migration_url
    conn = _connect(url)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(%s)", (_MIGRATION_LOCK_ID,))
        try:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    applied_at TEXT NOT NULL DEFAULT
                        to_char(now() AT TIME ZONE 'utc',
                                'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
                )"""
            )
            conn.commit()

            rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
            applied = {row["version"] for row in rows}

            migration_files = sorted(_PG_MIGRATIONS_DIR.glob("*.sql"))
            for mf in migration_files:
                if mf.name in applied:
                    continue
                sql_text = translate_placeholders(mf.read_text(encoding="utf-8"))
                try:
                    conn.execute(sql_text)
                    conn.execute(
                        "INSERT INTO schema_migrations (version, filename) "
                        "VALUES (%s, %s) ON CONFLICT (version) DO NOTHING",
                        (mf.name, mf.name),
                    )
                    conn.commit()
                except Exception as exc:
                    conn.rollback()
                    raise MigrationError(mf.name, exc) from exc
        finally:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s)", (_MIGRATION_LOCK_ID,))
            conn.commit()
    finally:
        conn.close()
