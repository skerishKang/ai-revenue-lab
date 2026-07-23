"""PostgreSQL migration runner (owner/migration role only).

Applies the hand-written PostgreSQL schema migrations in ``migrations_postgres/``
in sorted order. This runner is invoked ONLY by the explicit operator migration
command using ``LF_MIGRATION_DATABASE_URL`` (an owner/migration-role connection);
the runtime application never applies migrations and instead fails closed at
startup if the schema is missing or behind.

Safety properties:

* **Ordering** -- migrations apply in filename sort order and each applied
  version is recorded in ``schema_migrations``.
* **Checksum / tamper detection** -- the SHA-256 of each file is stored when
  applied; re-running against a changed file fails rather than silently
  diverging.
* **Idempotent re-apply** -- already-applied versions (matching checksum) are
  skipped, so the command is safe to re-run.
* **Concurrency** -- a PostgreSQL advisory lock serializes concurrent migration
  runs so two operators cannot apply migrations at once.
* **Fresh apply** -- ``CREATE ... IF NOT EXISTS`` makes a first run build the
  whole schema.

Statements are split with a dollar-quote-aware scanner so PL/pgSQL trigger
bodies (which contain semicolons inside ``$$ ... $$``) are kept intact. This is
migration-only SQL handling; the runtime adapter adapts statements differently.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from app.database.errors import SchemaMismatchError


class PostgresMigrationError(RuntimeError):
    def __init__(self, filename: str, original_error: Exception):
        self.filename = filename
        self.original_error = original_error
        super().__init__(f"postgres migration {filename} failed: {original_error}")


# Fixed 64-bit advisory-lock key identifying Living Fiction migrations. Any
# stable signed 64-bit integer works; this is derived deterministically so all
# operators contend on the same lock.
MIGRATION_LOCK_KEY = int.from_bytes(
    hashlib.sha256(b"living-fiction-postgres-migrations").digest()[:8],
    "big",
    signed=True,
)


def list_migrations(migrations_dir: str | Path) -> list[Path]:
    """Return migration ``*.sql`` files in sorted (apply) order."""
    return sorted(Path(migrations_dir).glob("*.sql"), key=lambda p: p.name)


def expected_versions(migrations_dir: str | Path) -> list[str]:
    """Return the ordered list of migration versions (filenames) on disk."""
    return [p.name for p in list_migrations(migrations_dir)]


def file_checksum(path: Path) -> str:
    """SHA-256 hex digest of a migration file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def split_statements(sql: str) -> list[str]:
    """Split a PostgreSQL script into individual statements.

    Understands single-quoted strings (``''`` escapes), double-quoted
    identifiers (``""`` escapes), line comments (``--``), block comments
    (``/* */``), and dollar-quoted bodies (``$tag$ ... $tag$``) so semicolons
    inside any of those do not terminate a statement.
    """
    statements: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            buf.append(ch)
            i += 1
            while i < n and sql[i] not in ("\n", "\r"):
                buf.append(sql[i])
                i += 1
        elif ch == "/" and i + 1 < n and sql[i + 1] == "*":
            buf.append(ch)
            buf.append(sql[i + 1])
            i += 2
            while i + 1 < n and not (sql[i] == "*" and sql[i + 1] == "/"):
                buf.append(sql[i])
                i += 1
            if i + 1 < n:
                buf.append(sql[i])
                buf.append(sql[i + 1])
                i += 2
        elif ch == "'":
            buf.append(ch)
            i += 1
            while i < n:
                buf.append(sql[i])
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        buf.append(sql[i + 1])
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
        elif ch == '"':
            buf.append(ch)
            i += 1
            while i < n:
                buf.append(sql[i])
                if sql[i] == '"':
                    if i + 1 < n and sql[i + 1] == '"':
                        buf.append(sql[i + 1])
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
        elif ch == "$":
            tag = _read_dollar_tag(sql, i)
            if tag is not None:
                opener = f"${tag}$"
                buf.append(opener)
                i += len(opener)
                closer = opener
                close_idx = sql.find(closer, i)
                if close_idx == -1:
                    buf.append(sql[i:])
                    i = n
                else:
                    buf.append(sql[i:close_idx])
                    buf.append(closer)
                    i = close_idx + len(closer)
            else:
                buf.append(ch)
                i += 1
        elif ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf.clear()
            i += 1
        else:
            buf.append(ch)
            i += 1
    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def _read_dollar_tag(sql: str, start: int) -> str | None:
    """If ``sql[start:]`` begins with a ``$tag$`` opener, return ``tag``.

    ``tag`` is zero or more identifier characters. Returns ``None`` when the
    ``$`` is not the start of a dollar-quote (e.g. a stray ``$``).
    """
    i = start + 1
    n = len(sql)
    while i < n and (sql[i].isalnum() or sql[i] == "_"):
        i += 1
    if i < n and sql[i] == "$":
        return sql[start + 1 : i]
    return None


def _ensure_migration_table(raw: Any) -> None:
    """Create the migration bookkeeping table (DDL — apply path ONLY).

    This is the ONE place a migration object may be created, and it is reached
    exclusively from :func:`apply_migrations` (the operator migration command).
    The runtime verifier (:func:`verify_schema_current`) never calls this, so a
    read-only runtime role can verify the schema without CREATE rights and a
    failed verification never leaves a new object behind.
    """
    raw.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            checksum TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def applied_migrations(conn: Any) -> dict[str, str]:
    """Return ``{version: checksum}`` for all applied migrations.

    APPLY-PATH helper: ensures the bookkeeping table exists first, so it must
    only be used from the operator migration command (owner/migration role).
    The runtime verifier uses :func:`read_applied_migrations` instead.

    Accepts a :class:`~app.database.postgres.PostgresConnection` (uses its raw
    connection) or a raw Psycopg connection with dict rows.
    """
    raw = getattr(conn, "raw", conn)
    _ensure_migration_table(raw)
    cur = raw.execute("SELECT version, checksum FROM schema_migrations")
    return {row["version"]: row["checksum"] for row in cur.fetchall()}


def read_applied_migrations(conn: Any) -> list[dict[str, Any]] | None:
    """READ-ONLY view of applied migrations; ``None`` when the table is absent.

    Uses only ``SELECT`` / catalog lookups so it is safe for a runtime role
    without CREATE rights and never mutates the database. Returns the raw rows
    (``[{"version": ..., "checksum": ...}, ...]``) WITHOUT de-duplicating so the
    caller can detect duplicate versions, or ``None`` when the
    ``schema_migrations`` table does not exist (schema never migrated).
    """
    raw = getattr(conn, "raw", conn)
    cur = raw.execute("SELECT to_regclass('schema_migrations') AS reg")
    row = cur.fetchone()
    reg = row["reg"] if isinstance(row, dict) else (row[0] if row else None)
    if reg is None:
        return None
    cur = raw.execute("SELECT version, checksum FROM schema_migrations")
    return [
        {"version": r["version"], "checksum": r["checksum"]} for r in cur.fetchall()
    ]


def apply_migrations(conn: Any, migrations_dir: str | Path) -> list[str]:
    """Apply pending PostgreSQL migrations under an advisory lock.

    Returns the list of newly applied versions. Raises
    :class:`PostgresMigrationError` on any failure (the offending transaction is
    rolled back) and on checksum mismatch for a previously applied file.
    """
    raw = getattr(conn, "raw", conn)
    raw.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_KEY,))
    try:
        _ensure_migration_table(raw)
        applied = applied_migrations(raw)
        newly: list[str] = []
        for path in list_migrations(migrations_dir):
            version = path.name
            checksum = file_checksum(path)
            if version in applied:
                if applied[version] != checksum:
                    raise PostgresMigrationError(
                        version,
                        RuntimeError(
                            "checksum mismatch: migration file changed after "
                            "it was applied"
                        ),
                    )
                continue
            try:
                statements = split_statements(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError) as exc:
                raise PostgresMigrationError(version, exc) from exc
            raw.execute("BEGIN")
            try:
                for stmt in statements:
                    raw.execute(stmt)
                raw.execute(
                    "INSERT INTO schema_migrations (version, checksum) "
                    "VALUES (%s, %s)",
                    (version, checksum),
                )
                raw.execute("COMMIT")
            except Exception as exc:
                raw.execute("ROLLBACK")
                raise PostgresMigrationError(version, exc) from exc
            newly.append(version)
        return newly
    finally:
        raw.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK_KEY,))


def verify_schema_current(conn: Any, migrations_dir: str | Path) -> None:
    """Fail closed unless the schema exactly matches the on-disk migrations.

    FULLY READ-ONLY: uses only ``SELECT`` / catalog lookups (via
    :func:`read_applied_migrations`) and never creates or mutates any object, so
    a runtime role without CREATE/ALTER/DROP rights can verify a current schema
    and a failed verification leaves the database byte-for-byte unchanged.

    Used by production startup. Fails closed (raises
    :class:`~app.database.errors.SchemaMismatchError`) on any of:

    * the ``schema_migrations`` table is absent (never migrated);
    * a stored version has no matching on-disk file (``unknown``);
    * an on-disk migration is not applied (``missing``);
    * a version is recorded more than once (``duplicate``);
    * a stored checksum differs from the on-disk file SHA-256
      (``checksum_mismatch``).

    The runtime app never applies migrations itself. Error messages contain only
    counts — never the DB URL, user, host, or password.
    """
    on_disk = list_migrations(migrations_dir)
    expected_checksums = {path.name: file_checksum(path) for path in on_disk}
    expected_set = set(expected_checksums)

    rows = read_applied_migrations(conn)
    if rows is None:
        raise SchemaMismatchError(
            "database schema is not current (migration table absent); "
            "run the migration command before starting the app"
        )

    stored: dict[str, str] = {}
    duplicate_count = 0
    for row in rows:
        version = row["version"]
        if version in stored:
            duplicate_count += 1
            continue
        stored[version] = row["checksum"]
    applied_set = set(stored)

    missing = sorted(expected_set - applied_set)
    unknown = sorted(applied_set - expected_set)
    checksum_mismatch = sorted(
        version
        for version in (expected_set & applied_set)
        if stored[version] != expected_checksums[version]
    )

    if missing or unknown or duplicate_count or checksum_mismatch:
        detail = []
        if missing:
            detail.append(f"missing={len(missing)}")
        if unknown:
            detail.append(f"unknown={len(unknown)}")
        if duplicate_count:
            detail.append(f"duplicate={duplicate_count}")
        if checksum_mismatch:
            detail.append(f"checksum_mismatch={len(checksum_mismatch)}")
        raise SchemaMismatchError(
            "database schema is not current (" + ", ".join(detail) + "); "
            "run the migration command before starting the app"
        )
