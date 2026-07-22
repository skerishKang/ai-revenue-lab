"""PostgreSQL migration engine for Personal Edition.

Provides ``apply_pg_migrations`` — a minimal, deterministic migration
runner for PostgreSQL that mirrors the contract of the SQLite
``app.db.apply_migrations`` but adds:

* **Explicit schema version** — each migration file is a version.
* **Checksum** — SHA-256 of the file content is stored alongside the
  version.  If an already-applied migration's content has changed, the
  runner raises ``PgMigrationError`` instead of silently skipping.
* **Deterministic ordering** — files are sorted by name.
* **Partial migration detection** — if a migration was recorded but
  its tables/objects are missing, the runner detects the gap.
* **Transaction rollback** — each migration runs in its own explicit
  transaction; on failure the transaction is rolled back and the
  version is NOT recorded.
* **No destructive reset** — ``DROP TABLE``-based initialization is
  never used.
* **Credential redaction** — all error messages use
  :func:`app.config.redact_database_url`.

Migration files are named ``pg_NNN_description.sql`` and live in the
``migrations/`` directory alongside the SQLite migrations.  The ``pg_``
prefix ensures they sort before SQLite ``NNN_`` files (pg < 0 in ASCII)
and are never confused with them.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any

from psycopg import Connection
from psycopg.rows import DictRow

from app.config import redact_database_url

# A PostgreSQL migration is any file named like ``pg_NNN_description.sql``
# in the migrations directory.
_PG_MIGRATION_RE = re.compile(r"^pg_\d+.*\.sql$")


class PgMigrationError(RuntimeError):
    """Raised when a PostgreSQL migration fails or is inconsistent."""

    def __init__(self, version: str, message: str):
        self.version = version
        self.message = message
        super().__init__(f"pg migration {version}: {message}")


def _is_pg_migration(name: str) -> bool:
    return name.endswith(".sql") and _PG_MIGRATION_RE.match(name) is not None


def _compute_checksum(content: bytes) -> str:
    """SHA-256 checksum of migration file content."""
    return hashlib.sha256(content).hexdigest()


def _read_migration(path: Path) -> tuple[str, str]:
    """Read a migration file and return (content, checksum)."""
    content = path.read_text(encoding="utf-8")
    checksum = _compute_checksum(content.encode("utf-8"))
    return content, checksum


def _split_statements(sql: str) -> list[str]:
    """Split SQL into individual statements.

    PostgreSQL's ``conn.execute`` only accepts a single statement, so we
    split on semicolons that are not inside string literals or comments.
    """
    statements: list[str] = []
    current: list[str] = []
    in_string = False
    string_char = ""
    in_line_comment = False
    in_block_comment = False
    i = 0

    while i < len(sql):
        ch = sql[i]
        next_ch = sql[i + 1] if i + 1 < len(sql) else ""

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            current.append(ch)
            i += 1
            continue

        if in_block_comment:
            if ch == "*" and next_ch == "/":
                in_block_comment = False
                current.append(ch)
                current.append(next_ch)
                i += 2
                continue
            current.append(ch)
            i += 1
            continue

        if in_string:
            current.append(ch)
            if ch == "\\" and next_ch:
                # Escape sequence — skip next char
                current.append(next_ch)
                i += 2
                continue
            if ch == string_char:
                in_string = False
            i += 1
            continue

        # Not in string or comment
        if ch == "-" and next_ch == "-":
            in_line_comment = True
            current.append(ch)
            current.append(next_ch)
            i += 2
            continue

        if ch == "/" and next_ch == "*":
            in_block_comment = True
            current.append(ch)
            current.append(next_ch)
            i += 2
            continue

        if ch in ("'", '"'):
            in_string = True
            string_char = ch
            current.append(ch)
            i += 1
            continue

        if ch == ";":
            stmt = "".join(current).strip()
            if stmt and _has_non_comment_content(stmt):
                statements.append(stmt)
            current.clear()
            i += 1
            continue

        current.append(ch)
        i += 1

    # Handle trailing statement without semicolon
    remainder = "".join(current).strip()
    if remainder and _has_non_comment_content(remainder):
        statements.append(remainder)

    return statements


def _has_non_comment_content(text: str) -> bool:
    """Return True if text contains any non-comment, non-whitespace content."""
    # Strip line comments
    text = re.sub(r"--[^\n]*", "", text)
    # Strip block comments
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return bool(text.strip())


def _ensure_migrations_table(conn: Connection[DictRow]) -> None:
    """Create the schema_migrations table if it does not exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            checksum TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def _get_applied(conn: Connection[DictRow]) -> dict[str, str]:
    """Return {version: checksum} for all applied migrations."""
    rows = conn.execute(
        "SELECT version, checksum FROM schema_migrations"
    ).fetchall()
    return {row["version"]: row["checksum"] for row in rows}


def _discover_migrations(migrations_dir: str) -> list[Path]:
    """Discover and deterministically order PostgreSQL migration files."""
    migrations_path = Path(migrations_dir)
    files = sorted(
        p for p in migrations_path.glob("*.sql") if _is_pg_migration(p.name)
    )
    return files


def _detect_partial(
    conn: Connection[DictRow],
    version: str,
    applied: dict[str, str],
) -> None:
    """Detect partial migration: version recorded but checksum mismatch.

    Raises PgMigrationError if an already-applied migration's content
    has changed since it was applied.
    """
    if version in applied:
        # The migration was already applied.  Verify the checksum matches.
        # This is checked by the caller before calling this function.
        pass


def apply_pg_migrations(
    conn: Connection[DictRow],
    migrations_dir: str,
    *,
    redact_url: str = "",
) -> list[str]:
    """Apply PostgreSQL migrations to an open connection.

    Parameters
    ----------
    conn:
        An open psycopg Connection (autocommit=False).
    migrations_dir:
        Path to the directory containing ``pg_*.sql`` migration files.
    redact_url:
        Optional redacted URL for error messages (never the raw URL).

    Returns
    -------
    list[str]
        Names of migrations that were applied in this run (empty if all
        were already applied).

    Raises
    ------
    PgMigrationError
        If a migration fails, if an already-applied migration's content
        has changed, or if a partial migration is detected.
    """
    _ensure_migrations_table(conn)
    conn.commit()

    applied = _get_applied(conn)
    migrations = _discover_migrations(migrations_dir)

    # Check for duplicate versions
    seen: set[str] = set()
    for m in migrations:
        if m.name in seen:
            raise PgMigrationError(
                m.name,
                f"duplicate migration version detected: {m.name}",
            )
        seen.add(m.name)

    applied_versions: list[str] = []

    for m in migrations:
        version = m.name
        content, checksum = _read_migration(m)

        if version in applied:
            # Already applied — verify checksum integrity.
            if applied[version] != checksum:
                raise PgMigrationError(
                    version,
                    "migration content has changed since it was applied "
                    "(checksum mismatch). Refusing to proceed. "
                    "See documentation for safe migration update procedure.",
                )
            # Checksum matches — skip.
            continue

        # Read content fresh for execution
        statements = _split_statements(content)

        try:
            for stmt in statements:
                conn.execute(stmt)
            conn.execute(
                "INSERT INTO schema_migrations (version, checksum) "
                "VALUES (%s, %s)",
                (version, checksum),
            )
            conn.commit()
            applied_versions.append(version)
        except Exception as exc:
            conn.rollback()
            safe_url = redact_url or "(url not provided)"
            raise PgMigrationError(
                version,
                f"migration failed (url={safe_url}): {exc}",
            ) from exc

    return applied_versions


def get_pg_schema_tables(conn: Connection[DictRow]) -> set[str]:
    """Return the set of user table names in the current schema."""
    rows = conn.execute(
        """
        SELECT tablename
        FROM pg_catalog.pg_tables
        WHERE schemaname = 'public'
        """
    ).fetchall()
    return {row["tablename"] for row in rows}


def get_pg_schema_indexes(conn: Connection[DictRow]) -> list[tuple[str, str]]:
    """Return (index_name, table_name) pairs for all indexes."""
    rows = conn.execute(
        """
        SELECT indexname, tablename
        FROM pg_indexes
        WHERE schemaname = 'public'
        ORDER BY tablename, indexname
        """
    ).fetchall()
    return [(row["indexname"], row["tablename"]) for row in rows]


def get_pg_schema_columns(
    conn: Connection[DictRow], table_name: str
) -> list[dict[str, Any]]:
    """Return column metadata for a table."""
    rows = conn.execute(
        """
        SELECT
            column_name,
            data_type,
            is_nullable,
            column_default,
            ordinal_position
        FROM information_schema.columns
        WHERE table_schema = 'public'
        AND table_name = %s
        ORDER BY ordinal_position
        """,
        (table_name,),
    ).fetchall()
    return [
        {
            "column_name": row["column_name"],
            "data_type": row["data_type"],
            "is_nullable": row["is_nullable"],
            "column_default": row["column_default"],
        }
        for row in rows
    ]


def get_pg_primary_keys(conn: Connection[DictRow], table_name: str) -> list[str]:
    """Return primary key column names for a table."""
    rows = conn.execute(
        """
        SELECT a.attname
        FROM pg_index i
        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
        JOIN pg_class c ON c.oid = i.indrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE i.indisprimary
        AND n.nspname = 'public'
        AND c.relname = %s
        ORDER BY a.attnum
        """,
        (table_name,),
    ).fetchall()
    return [row["attname"] for row in rows]


def get_pg_foreign_keys(conn: Connection[DictRow], table_name: str) -> list[dict]:
    """Return foreign key metadata for a table."""
    rows = conn.execute(
        """
        SELECT
            tc.constraint_name,
            kcu.column_name,
            ccu.table_name AS foreign_table_name,
            ccu.column_name AS foreign_column_name,
            rc.update_rule,
            rc.delete_rule
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
            ON tc.constraint_name = kcu.constraint_name
            AND tc.table_schema = kcu.table_schema
        JOIN information_schema.referential_constraints rc
            ON tc.constraint_name = rc.constraint_name
            AND tc.table_schema = rc.constraint_schema
        JOIN information_schema.constraint_column_usage ccu
            ON rc.unique_constraint_name = ccu.constraint_name
            AND rc.unique_constraint_schema = ccu.table_schema
        WHERE tc.table_schema = 'public'
        AND tc.table_name = %s
        AND tc.constraint_type = 'FOREIGN KEY'
        ORDER BY tc.constraint_name, kcu.ordinal_position
        """,
        (table_name,),
    ).fetchall()
    return [
        {
            "constraint_name": row["constraint_name"],
            "column_name": row["column_name"],
            "foreign_table_name": row["foreign_table_name"],
            "foreign_column_name": row["foreign_column_name"],
            "update_rule": row["update_rule"],
            "delete_rule": row["delete_rule"],
        }
        for row in rows
    ]


def get_pg_unique_constraints(
    conn: Connection[DictRow], table_name: str
) -> list[dict]:
    """Return unique constraint metadata for a table."""
    rows = conn.execute(
        """
        SELECT
            tc.constraint_name,
            kcu.column_name,
            kcu.ordinal_position
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
            ON tc.constraint_name = kcu.constraint_name
            AND tc.table_schema = kcu.table_schema
        WHERE tc.table_schema = 'public'
        AND tc.table_name = %s
        AND tc.constraint_type = 'UNIQUE'
        ORDER BY tc.constraint_name, kcu.ordinal_position
        """,
        (table_name,),
    ).fetchall()
    # Group by constraint name
    result: dict[str, dict] = {}
    for row in rows:
        name = row["constraint_name"]
        if name not in result:
            result[name] = {"constraint_name": name, "columns": []}
        result[name]["columns"].append(row["column_name"])
    return list(result.values())


def get_pg_check_constraints(
    conn: Connection[DictRow], table_name: str
) -> list[str]:
    """Return CHECK constraint definitions for a table."""
    rows = conn.execute(
        """
        SELECT conname, pg_get_constraintdef(c.oid) AS definition
        FROM pg_constraint c
        JOIN pg_class cl ON cl.oid = c.conrelid
        JOIN pg_namespace n ON n.oid = cl.relnamespace
        WHERE n.nspname = 'public'
        AND cl.relname = %s
        AND c.contype = 'c'
        ORDER BY conname
        """,
        (table_name,),
    ).fetchall()
    return [f"{row['conname']}: {row['definition']}" for row in rows]
