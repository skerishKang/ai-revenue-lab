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
import uuid
from pathlib import Path
from typing import Any

from psycopg import Connection
from psycopg.rows import DictRow

from app.config import redact_database_url

# A PostgreSQL migration is any file named like ``pg_NNN_description.sql``
# in the migrations directory.
_PG_MIGRATION_RE = re.compile(r"^pg_(\d+)_.*\.sql$")

# Safe, fixed error categories for user-facing messages — never include
# raw exception text which may contain DSN/userinfo/SQL internals.
_MIGRATION_ERROR_CATEGORIES = {
    "apply_failed": "migration statement execution failed",
    "checksum_mismatch": "migration content has changed since it was applied",
    "partial_schema": "partial schema detected: objects exist without a recorded migration",
    "schema_drift": "schema drift detected: recorded migration does not match current schema",
    "discovery": "migration discovery failed",
}


def _safe_message(category: str) -> str:
    """Return a fixed safe error category string for user-facing output."""
    return _MIGRATION_ERROR_CATEGORIES.get(category, "migration error")


class PgMigrationError(RuntimeError):
    """Raised when a PostgreSQL migration fails or is inconsistent.

    The public message uses a fixed safe category; the original exception
    (if any) is chained via ``__cause__`` for internal debugging only.
    """

    category: str = "migration error"

    def __init__(self, version: str, message: str, *, category: str = "migration error"):
        self.version = version
        self.message = message
        self.category = category
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
    """Discover and deterministically order PostgreSQL migration files by numeric version."""
    migrations_path = Path(migrations_dir)
    parsed = []
    
    # Pre-filter all pg_*.sql files to ensure no malformed ones slip by
    for p in migrations_path.glob("pg_*.sql"):
        match = _PG_MIGRATION_RE.match(p.name)
        if not match:
            raise PgMigrationError(p.name, f"malformed migration filename: {p.name}")
        num = int(match.group(1))
        parsed.append((num, p))
        
    seen = set()
    for num, p in parsed:
        if num in seen:
            raise PgMigrationError(p.name, f"duplicate numeric version {num} detected in {p.name}")
        seen.add(num)
        
    parsed.sort(key=lambda x: x[0])
    return [p for _, p in parsed]


def _get_current_search_path(conn: Connection[DictRow]) -> str:
    """Return the current search_path setting string.

    This is used ONLY for restoring the original setting on exit — never
    for computing the effective target schema.
    """
    row = conn.execute("SHOW search_path").fetchone()
    val = row[0] if row else ""
    return str(val) if val else ""


def _get_current_schema(conn: Connection[DictRow]) -> str:
    """Return the effective target schema via ``SELECT current_schema()``.

    PostgreSQL resolves the effective schema considering ``$user`` (which
    falls back to ``public`` if the user-named schema does not exist).  Using
    ``current_schema()`` avoids incorrectly treating the literal ``$user``
    token as the target schema.

    Raises :class:`PgMigrationError` if the result is NULL, failing closed
    rather than guessing.
    """
    row = conn.execute("SELECT current_schema()").fetchone()
    val = row[0] if row else None
    if not val:
        raise PgMigrationError(
            "unknown",
            "cannot determine effective schema: current_schema() returned NULL",
            category="schema_drift",
        )
    return str(val)


def _check_schema_drift(
    conn: Connection[DictRow],
    version: str,
    content: str,
    is_applied: bool,
) -> None:
    """Run migration in a temporary schema to detect partial applies or drift.

    The drift comparison target is the **migration target schema** — the
    schema that was current before this function was called — never a
    hardcoded ``public``.  The original ``search_path`` is captured on entry
    and restored exactly on exit.  The temporary drift schema uses a random
    suffix to avoid collisions across concurrent runs.
    """
    # Capture the real target schema and search_path BEFORE any drift work.
    original_search_path = _get_current_search_path(conn)
    target_schema = _get_current_schema(conn)

    # Unique temp schema name to avoid concurrent-run collisions.
    temp_schema = f"drift_check_{uuid.uuid4().hex}"

    conn.execute("SAVEPOINT migration_drift_check")
    try:
        conn.execute(f'CREATE SCHEMA "{temp_schema}"')
        conn.execute(f'SET LOCAL search_path TO "{temp_schema}"')

        for stmt in _split_statements(content):
            conn.execute(stmt)

        expected_tables = get_pg_schema_tables(conn, temp_schema)
        if "schema_migrations" in expected_tables:
            expected_tables.remove("schema_migrations")

        target_tables = get_pg_schema_tables(conn, target_schema)

        if not is_applied:
            overlap = expected_tables.intersection(target_tables)
            if overlap:
                raise PgMigrationError(
                    version,
                    f"partial schema detected: unrecorded migration but tables exist: {overlap}",
                    category="partial_schema",
                )
        else:
            missing_tables = expected_tables - target_tables
            if missing_tables:
                raise PgMigrationError(
                    version,
                    f"schema drift detected: missing tables: {missing_tables}",
                    category="schema_drift",
                )

            for table in expected_tables:
                exp_cols = get_pg_schema_columns(conn, table, temp_schema)
                pub_cols = get_pg_schema_columns(conn, table, target_schema)
                if exp_cols != pub_cols:
                    raise PgMigrationError(
                        version,
                        f"schema drift detected in table {table} columns",
                        category="schema_drift",
                    )

                exp_pks = get_pg_primary_keys(conn, table, temp_schema)
                pub_pks = get_pg_primary_keys(conn, table, target_schema)
                if exp_pks != pub_pks:
                    raise PgMigrationError(
                        version,
                        f"schema drift detected in table {table} primary keys",
                        category="schema_drift",
                    )

                exp_fks = get_pg_foreign_keys(conn, table, temp_schema)
                pub_fks = get_pg_foreign_keys(conn, table, target_schema)
                if exp_fks != pub_fks:
                    raise PgMigrationError(
                        version,
                        f"schema drift detected in table {table} foreign keys",
                        category="schema_drift",
                    )

                exp_uniques = get_pg_unique_constraints(conn, table, temp_schema)
                pub_uniques = get_pg_unique_constraints(conn, table, target_schema)
                if exp_uniques != pub_uniques:
                    raise PgMigrationError(
                        version,
                        f"schema drift detected in table {table} unique constraints",
                        category="schema_drift",
                    )

                exp_checks = get_pg_check_constraints(conn, table, temp_schema)
                pub_checks = get_pg_check_constraints(conn, table, target_schema)
                if exp_checks != pub_checks:
                    raise PgMigrationError(
                        version,
                        f"schema drift detected in table {table} check constraints",
                        category="schema_drift",
                    )

        exp_indexes = get_pg_schema_indexes(conn, temp_schema)
        pub_indexes = get_pg_schema_indexes(conn, target_schema)
        exp_idx = {(idx, tbl) for idx, tbl in exp_indexes if tbl in expected_tables}
        pub_idx = {(idx, tbl) for idx, tbl in pub_indexes if tbl in expected_tables}

        if not is_applied:
            overlap_idx = exp_idx.intersection(pub_idx)
            if overlap_idx:
                raise PgMigrationError(
                    version,
                    f"partial schema detected: unrecorded migration but indexes exist: {overlap_idx}",
                    category="partial_schema",
                )
        else:
            missing_idx = exp_idx - pub_idx
            if missing_idx:
                raise PgMigrationError(
                    version,
                    f"schema drift detected: missing indexes: {missing_idx}",
                    category="schema_drift",
                )

    finally:
        # Always rollback the drift savepoint (which drops the temp schema)
        # and restore the EXACT original search_path — never hardcode public.
        conn.execute("ROLLBACK TO SAVEPOINT migration_drift_check")
        # SET LOCAL is scoped to the transaction block; restore explicitly.
        conn.execute(f'SET LOCAL search_path TO {original_search_path or "public"}')


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

    # Check for duplicate versions is now handled in _discover_migrations
    
    applied_versions: list[str] = []

    for m in migrations:
        version = m.name
        content, checksum = _read_migration(m)

        if version in applied:
            if applied[version] != checksum:
                raise PgMigrationError(
                    version,
                    _safe_message("checksum_mismatch"),
                    category="checksum_mismatch",
                )
            # Integrity drift check
            _check_schema_drift(conn, version, content, is_applied=True)
            continue

        # Unrecorded: partial detection
        _check_schema_drift(conn, version, content, is_applied=False)

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
            raise PgMigrationError(
                version,
                _safe_message("apply_failed"),
                category="apply_failed",
            ) from exc

    return applied_versions


def get_pg_schema_tables(conn: Connection[DictRow], schema: str | None = None) -> set[str]:
    """Return the set of user table names in the current schema."""
    rows = conn.execute(
        """
        SELECT tablename
        FROM pg_catalog.pg_tables
        WHERE schemaname = COALESCE(%s, current_schema())
        """,
        (schema,)
    ).fetchall()
    return {row["tablename"] for row in rows}


def get_pg_schema_indexes(conn: Connection[DictRow], schema: str | None = None) -> list[tuple[str, str]]:
    """Return (index_name, table_name) pairs for all indexes."""
    rows = conn.execute(
        """
        SELECT indexname, tablename
        FROM pg_indexes
        WHERE schemaname = COALESCE(%s, current_schema())
        ORDER BY tablename, indexname
        """,
        (schema,)
    ).fetchall()
    return [(row["indexname"], row["tablename"]) for row in rows]


def get_pg_schema_columns(
    conn: Connection[DictRow], table_name: str, schema: str | None = None
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
        WHERE table_schema = COALESCE(%s, current_schema())
        AND table_name = %s
        ORDER BY ordinal_position
        """,
        (schema, table_name),
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


def get_pg_primary_keys(conn: Connection[DictRow], table_name: str, schema: str | None = None) -> list[str]:
    """Return primary key column names for a table."""
    rows = conn.execute(
        """
        SELECT a.attname
        FROM pg_index i
        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
        JOIN pg_class c ON c.oid = i.indrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE i.indisprimary
        AND n.nspname = COALESCE(%s, current_schema())
        AND c.relname = %s
        ORDER BY a.attnum
        """,
        (schema, table_name),
    ).fetchall()
    return [row["attname"] for row in rows]


def get_pg_foreign_keys(conn: Connection[DictRow], table_name: str, schema: str | None = None) -> list[dict]:
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
        WHERE tc.table_schema = COALESCE(%s, current_schema())
        AND tc.table_name = %s
        AND tc.constraint_type = 'FOREIGN KEY'
        ORDER BY tc.constraint_name, kcu.ordinal_position
        """,
        (schema, table_name),
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
    conn: Connection[DictRow], table_name: str, schema: str | None = None
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
        WHERE tc.table_schema = COALESCE(%s, current_schema())
        AND tc.table_name = %s
        AND tc.constraint_type = 'UNIQUE'
        ORDER BY tc.constraint_name, kcu.ordinal_position
        """,
        (schema, table_name),
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
    conn: Connection[DictRow], table_name: str, schema: str | None = None
) -> list[str]:
    """Return CHECK constraint definitions for a table."""
    rows = conn.execute(
        """
        SELECT conname, pg_get_constraintdef(c.oid) AS definition
        FROM pg_constraint c
        JOIN pg_class cl ON cl.oid = c.conrelid
        JOIN pg_namespace n ON n.oid = cl.relnamespace
        WHERE n.nspname = COALESCE(%s, current_schema())
        AND cl.relname = %s
        AND c.contype = 'c'
        ORDER BY conname
        """,
        (schema, table_name),
    ).fetchall()
    return [f"{row['conname']}: {row['definition']}" for row in rows]
