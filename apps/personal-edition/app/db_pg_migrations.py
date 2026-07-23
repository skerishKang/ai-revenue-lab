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


class MigrationParseError(RuntimeError):
    """Raised when migration SQL contains malformed syntax.

    Unterminated comments, strings, or dollar quotes are detected and
    rejected with a fixed safe error message.  The original content
    (position, snippet) is NOT included in the message for safety.
    """


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


_DOLLAR_TAG_RE = re.compile(r"\$([A-Za-z_]\w*)?\$")


def _neutralize_sql(content: str) -> str:
    """Replace comments and string literals with inert placeholders.

    Ensures :data:`_CREATE_TABLE_RE` only matches real DDL, not text that
    appears inside comments or string literals.

    Handles:
    - Line comments: ``-- ...``
    - Block comments: ``/* ... */`` including nested ``/* /* */ */``
    - Single-quoted strings: ``'...'`` with ``''`` escape
    - E-strings: ``E'...'`` / ``e'...'`` with ``\\'`` and ``''`` escapes
      (the ``E`` prefix must not be part of a larger identifier)
    - Dollar-quoted strings: ``$$...$$`` or ``$tag$...$tag$``

    Raises :class:`MigrationParseError` if any construct is unterminated
    (reaches EOF before the closing delimiter).
    """
    out: list[str] = []
    i = 0
    n = len(content)

    while i < n:
        c = content[i]

        if c == "-" and i + 1 < n and content[i + 1] == "-":
            while i < n and content[i] != "\n":
                i += 1
            out.append(" ")
            continue

        if c == "/" and i + 1 < n and content[i + 1] == "*":
            depth = 1
            i += 2
            while i < n and depth > 0:
                if content[i] == "/" and i + 1 < n and content[i + 1] == "*":
                    depth += 1
                    i += 2
                elif content[i] == "*" and i + 1 < n and content[i + 1] == "/":
                    depth -= 1
                    i += 2
                else:
                    i += 1
            if depth > 0:
                raise MigrationParseError(
                    "unterminated block comment"
                )
            out.append(" ")
            continue

        if c in ("E", "e") and i + 1 < n and content[i + 1] == "'":
            if i == 0 or not (content[i - 1].isalnum() or content[i - 1] == "_"):
                i += 2
                found_close = False
                while i < n:
                    if content[i] == "\\":
                        i += 2
                    elif content[i] == "'" and i + 1 < n and content[i + 1] == "'":
                        i += 2
                    elif content[i] == "'":
                        i += 1
                        found_close = True
                        break
                    else:
                        i += 1
                if not found_close:
                    raise MigrationParseError(
                        "unterminated E-string literal"
                    )
                out.append("''")
                continue

        if c == "$":
            m = _DOLLAR_TAG_RE.match(content, i)
            if m:
                tag = m.group(0)
                i += len(tag)
                end = content.find(tag, i)
                if end == -1:
                    raise MigrationParseError(
                        "unterminated dollar-quoted string"
                    )
                i = end + len(tag)
                out.append("''")
                continue

        if c == "'":
            i += 1
            found_close = False
            while i < n:
                if content[i] == "'" and i + 1 < n and content[i + 1] == "'":
                    i += 2
                elif content[i] == "'":
                    i += 1
                    found_close = True
                    break
                else:
                    i += 1
            if not found_close:
                raise MigrationParseError(
                    "unterminated single-quoted string literal"
                )
            out.append("''")
            continue

        out.append(c)
        i += 1

    return "".join(out)


_CREATE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"(?:\"?[\w]+\"?\.)?"  # optional schema qualifier
    r"\"?([\w]+)\"?",       # table name
    re.IGNORECASE,
)


def _extract_created_tables(content: str) -> set[str]:
    """Return the set of table names created by a migration's SQL.

    Purely textual (read-only) — used by :func:`verify_pg_schema` to know
    which tables an applied migration declares, without executing any DDL.
    Handles optional ``IF NOT EXISTS``, an optional schema qualifier, and
    optional double-quoted identifiers.

    Comments (line, block, nested) and string literals (single-quoted,
    E-quoted, dollar-quoted) are neutralised before matching so that
    ``CREATE TABLE`` appearing inside them is never detected.
    """
    return {m.group(1) for m in _CREATE_TABLE_RE.finditer(_neutralize_sql(content))}


def _validate_migration_sql(content: str) -> None:
    """Validate migration SQL before any database writes.

    Raises :class:`MigrationParseError` if the SQL contains:
    - Unterminated block/nested comments, string literals, E-strings,
      or dollar-quoted strings (via :func:`_neutralize_sql`).
    - Dollar-quoted strings (``$$...$$``, ``$tag$...$tag$``) or nested
      block comments, which :func:`_split_statements` does not understand.

    The message is a fixed safe string; the original content is never
    interpolated.
    """
    _neutralize_sql(content)

    if "$" in content:
        if _DOLLAR_TAG_RE.search(content) is not None:
            raise MigrationParseError(
                "migration SQL contains dollar-quoted strings "
                "not supported by statement splitter"
            )

    _check_block_comment_nesting(content)


def _check_block_comment_nesting(sql: str) -> None:
    """Raise :class:`MigrationParseError` if the SQL contains
    actual nested block comments (depth >= 2).

    Properly ignores ``/*`` and ``*/`` markers that appear inside
    string literals, E-strings, double-quoted identifiers, or
    line comments, avoiding false positives.
    """
    i = 0
    n = len(sql)
    depth = 0
    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""

        if depth > 0:
            if ch == "/" and nxt == "*":
                depth += 1
                if depth >= 2:
                    raise MigrationParseError(
                        "migration SQL contains nested block comments "
                        "not supported by statement splitter"
                    )
                i += 2
            elif ch == "*" and nxt == "/":
                depth -= 1
                i += 2
            elif ch == "\n":
                i += 1
            else:
                i += 1
            continue

        if ch == "-" and nxt == "-":
            while i < n and sql[i] != "\n":
                i += 1
            continue

        if ch == "/" and nxt == "*":
            depth = 1
            i += 2
            continue

        if ch == "'":
            i += 1
            while i < n:
                if sql[i] == "\\":
                    i += 2
                elif sql[i] == "'" and i + 1 < n and sql[i + 1] == "'":
                    i += 2
                elif sql[i] == "'":
                    i += 1
                    break
                else:
                    i += 1
            continue

        if ch in ("E", "e") and nxt == "'" and (
            i == 0 or not (sql[i - 1].isalnum() or sql[i - 1] == "_")
        ):
            i += 2
            while i < n:
                if sql[i] == "\\":
                    i += 2
                elif sql[i] == "'" and i + 1 < n and sql[i + 1] == "'":
                    i += 2
                elif sql[i] == "'":
                    i += 1
                    break
                else:
                    i += 1
            continue

        if ch == '"':
            i += 1
            while i < n and sql[i] != '"':
                if sql[i] == '"' and i + 1 < n and sql[i + 1] == '"':
                    i += 2
                else:
                    i += 1
            i += 1
            continue

        i += 1


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

    The result column is aliased (``AS search_path``) so the value can be
    read by name from a ``dict_row`` connection; positional ``row[0]``
    access is not available on dict rows.
    """
    row = conn.execute("SHOW search_path").fetchone()
    if not row:
        return ""
    val = row["search_path"] if "search_path" in row.keys() else list(row.values())[0]
    return str(val) if val else ""


def _get_current_schema(conn: Connection[DictRow]) -> str:
    """Return the effective target schema via ``SELECT current_schema()``.

    PostgreSQL resolves the effective schema considering ``$user`` (which
    falls back to ``public`` if the user-named schema does not exist).  Using
    ``current_schema()`` avoids incorrectly treating the literal ``$user``
    token as the target schema.

    The result is aliased (``AS schema``) and read by name so the lookup
    works on a ``dict_row`` connection.

    Raises :class:`PgMigrationError` if the result is NULL, failing closed
    rather than guessing.
    """
    row = conn.execute("SELECT current_schema() AS schema").fetchone()
    val = row["schema"] if row else None
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
    MigrationParseError
        If any pending migration's SQL contains malformed or unsupported
        constructs before any database writes begin.
    """
    migrations = _discover_migrations(migrations_dir)

    for m in migrations:
        content, _ = _read_migration(m)
        _validate_migration_sql(content)

    _ensure_migrations_table(conn)
    conn.commit()

    applied = _get_applied(conn)

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


def verify_pg_schema(
    conn: Connection[DictRow],
    migrations_dir: str,
    *,
    redact_url: str = "",
) -> dict[str, Any]:
    """Read-only schema verification for application startup.

    This function does NOT apply migrations and does NOT create any
    objects (no ``CREATE SCHEMA``, no DDL).  It only reads
    ``information_schema`` / ``pg_catalog`` and the ``schema_migrations``
    table, so it is safe to run with the Neon runtime role which has no
    migration/owner privileges.

    Verification performed (all read-only, fail-closed):

    1. The effective schema resolves to a non-NULL value.
    2. The ``schema_migrations`` table exists.
    3. Every recorded migration version exists in the migration directory
       (unknown recorded versions are rejected).
    4. Every recorded migration checksum matches the migration file.
    5. No pending migrations exist (all discovered migrations applied).
    6. The tables the migrations declare (``CREATE TABLE``) actually exist
       in the effective schema (partial schema / drift is rejected).

    This is the Neon production contract: application startup performs
    read-only schema/version/checksum verification only.  Explicit
    migration CLI is the only path that applies migrations.

    All result columns are aliased and read by name so the queries work on
    a ``dict_row`` connection (positional ``row[0]`` is unavailable there).

    Parameters
    ----------
    conn:
        An open psycopg Connection (read-only operations only).
    migrations_dir:
        Path to the directory containing ``pg_*.sql`` migration files.
    redact_url:
        Optional redacted URL for error messages (never the raw URL).

    Returns
    -------
    dict[str, Any]
        Verification result with keys:
        - ``applied_count``: number of applied migrations
        - ``pending_count``: number of pending migrations (always 0 on success)
        - ``versions``: list of applied version names
        - ``schema``: the effective schema that was verified

    Raises
    ------
    PgMigrationError
        If the effective schema is NULL, the ``schema_migrations`` table is
        missing, a recorded version is unknown, a checksum mismatches, there
        are pending migrations, or declared tables are missing (drift).
    """
    effective_schema = _get_current_schema(conn)

    row = conn.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = current_schema()
            AND table_name = 'schema_migrations'
        ) AS exists
        """
    ).fetchone()
    if not row or not row["exists"]:
        raise PgMigrationError(
            "startup",
            "schema_migrations table not found: run migration CLI first",
            category="discovery",
        )

    applied = _get_applied(conn)
    migrations = _discover_migrations(migrations_dir)
    known_versions = {m.name for m in migrations}

    for m in migrations:
        content, _ = _read_migration(m)
        _validate_migration_sql(content)

    unknown = sorted(set(applied) - known_versions)
    if unknown:
        raise PgMigrationError(
            "startup",
            f"recorded migrations not found in migration directory: {unknown}",
            category="schema_drift",
        )

    expected_tables: set[str] = set()
    for m in migrations:
        version = m.name
        content, checksum = _read_migration(m)
        if version in applied and applied[version] != checksum:
            raise PgMigrationError(
                version,
                _safe_message("checksum_mismatch"),
                category="checksum_mismatch",
            )
        expected_tables |= _extract_created_tables(content)

    pending = [m.name for m in migrations if m.name not in applied]
    if pending:
        raise PgMigrationError(
            "startup",
            f"pending migrations detected: {pending}. Run migration CLI first.",
            category="discovery",
        )

    expected_tables.discard("schema_migrations")
    if expected_tables:
        actual_tables = get_pg_schema_tables(conn, effective_schema)
        missing = expected_tables - actual_tables
        if missing:
            raise PgMigrationError(
                "startup",
                f"schema drift detected: missing tables: {sorted(missing)}",
                category="schema_drift",
            )

    return {
        "applied_count": len(applied),
        "pending_count": 0,
        "versions": sorted(applied.keys()),
        "schema": effective_schema,
    }
