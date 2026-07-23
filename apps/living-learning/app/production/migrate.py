"""PostgreSQL migration runner (operator-only, fail-closed).

Applies the PostgreSQL migrations in ``migrations_postgres/`` using the
migration-owner direct URL (``LL_MIGRATION_DATABASE_URL``). Migrations are
serialized with a PostgreSQL advisory lock and recorded with a SHA-256 checksum
so a tampered or out-of-order migration fails closed. Re-runs are no-ops.

Usage:
    python -m app.production.migrate

The runtime app never calls this; it only verifies the schema is current
(read-only). Migration-owner credentials are kept out of the runtime app.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.production.database import ConfigurationError, connect_postgres

_MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "migrations_postgres"

# Deterministic advisory-lock key (no secret).
MIGRATION_LOCK_KEY = int.from_bytes(
    hashlib.sha256(b"living-learning-postgres-migrations").digest()[:8], "big", signed=True
)


class PostgresMigrationError(Exception):
    def __init__(self, version: str, original: Exception) -> None:
        self.version = version
        self.original = original
        super().__init__(f"PostgreSQL migration {version} failed: {original}")


def _file_checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def list_migrations(migrations_dir: Path = _MIGRATIONS_DIR) -> list[Path]:
    return sorted(migrations_dir.glob("*.sql"))


def split_statements(sql_text: str) -> list[str]:
    """Split SQL into statements, aware of single-quoted strings and
    dollar-quoted bodies ($tag$ ... $tag$) so PL/pgSQL survives."""
    statements: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(sql_text)
    in_single = False
    in_line_comment = False
    in_block_comment = False
    dollar_tag: str | None = None
    while i < n:
        ch = sql_text[i]
        if in_line_comment:
            buf.append(ch)
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue
        if in_block_comment:
            buf.append(ch)
            if sql_text[i : i + 2] == "*/":
                buf.append("*")
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue
        if dollar_tag is not None:
            buf.append(ch)
            if sql_text[i : i + len(dollar_tag)] == dollar_tag:
                buf.append(dollar_tag[1:])
                i += len(dollar_tag)
                dollar_tag = None
                continue
            i += 1
            continue
        if in_single:
            buf.append(ch)
            if ch == "'":
                if i + 1 < n and sql_text[i + 1] == "'":
                    buf.append("'")
                    i += 2
                    continue
                in_single = False
            i += 1
            continue
        # Not inside any quoted context.
        if sql_text[i : i + 2] == "--":
            in_line_comment = True
            buf.append(ch)
            i += 1
            continue
        if sql_text[i : i + 2] == "/*":
            in_block_comment = True
            buf.append(ch)
            i += 1
            continue
        if ch == "'":
            in_single = True
            buf.append(ch)
            i += 1
            continue
        if ch == "$":
            # Detect a dollar-quote tag: $tag$ (tag may be empty).
            j = i + 1
            tag_chars = []
            while j < n and (sql_text[j].isalnum() or sql_text[j] == "_"):
                tag_chars.append(sql_text[j])
                j += 1
            if j < n and sql_text[j] == "$":
                dollar_tag = "$" + "".join(tag_chars) + "$"
                buf.append(dollar_tag)
                i = j + 1
                continue
            buf.append(ch)
            i += 1
            continue
        if ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def _ensure_migration_table(raw) -> None:
    raw.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version TEXT PRIMARY KEY, checksum TEXT NOT NULL, "
        "applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )


def applied_migrations(raw) -> dict[str, str]:
    rows = raw.execute("SELECT version, checksum FROM schema_migrations").fetchall()
    return {r["version"]: r["checksum"] for r in rows}


def apply_migrations(conn, migrations_dir: Path = _MIGRATIONS_DIR) -> list[str]:
    """Apply pending migrations under an advisory lock. Returns applied versions."""
    raw = getattr(conn, "raw", conn)
    raw.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_KEY,))
    try:
        _ensure_migration_table(raw)
        applied = applied_migrations(raw)
        newly: list[str] = []
        for path in list_migrations(migrations_dir):
            version = path.name
            checksum = _file_checksum(path)
            if version in applied:
                if applied[version] != checksum:
                    raise PostgresMigrationError(
                        version, RuntimeError("checksum mismatch for already-applied migration")
                    )
                continue
            raw.execute("BEGIN")
            try:
                for stmt in split_statements(path.read_text(encoding="utf-8")):
                    raw.execute(stmt)
                raw.execute(
                    "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
                    (version, checksum),
                )
                raw.execute("COMMIT")
            except Exception as exc:  # noqa: BLE001
                raw.execute("ROLLBACK")
                raise PostgresMigrationError(version, exc) from exc
            newly.append(version)
        return newly
    finally:
        raw.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK_KEY,))


def verify_schema_current(conn, migrations_dir: Path = _MIGRATIONS_DIR) -> None:
    """Read-only check that all migrations are applied with matching checksums.

    Raises ``PostgresMigrationError`` (fail-closed) if any migration is missing,
    unknown, or has a checksum mismatch. Messages contain only counts/versions.
    """
    raw = getattr(conn, "raw", conn)
    _ensure_migration_table(raw)
    applied = applied_migrations(raw)
    expected = {p.name: _file_checksum(p) for p in list_migrations(migrations_dir)}
    missing = [v for v in expected if v not in applied]
    if missing:
        raise PostgresMigrationError(
            "<verify>", RuntimeError(f"schema behind: {len(missing)} migration(s) not applied")
        )
    mismatched = [v for v, c in expected.items() if applied.get(v) != c]
    if mismatched:
        raise PostgresMigrationError(
            "<verify>", RuntimeError(f"checksum mismatch for {len(mismatched)} migration(s)")
        )


def main() -> None:
    """CLI entry: apply PostgreSQL migrations using the migration-owner URL."""
    from app.config import get_settings

    settings = get_settings()
    url = settings.effective_migration_url
    if not url or not (url.startswith("postgresql://") or url.startswith("postgres://")):
        raise ConfigurationError(
            "migration requires a postgresql:// LL_MIGRATION_DATABASE_URL"
        )
    conn = connect_postgres(url, autocommit=True)
    try:
        applied = apply_migrations(conn)
        if applied:
            print(f"applied migrations: {', '.join(applied)}")
        else:
            print("schema already current; no migrations applied")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
