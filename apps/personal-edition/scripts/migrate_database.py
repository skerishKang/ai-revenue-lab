#!/usr/bin/env python3
"""Database migration entry point for Personal Edition.

Usage:

    # SQLite (default):
    python -m scripts.migrate_database

    # PostgreSQL (explicit):
    python -m scripts.migrate_database --backend postgresql --url postgresql://...

    # Dry run (show what would be applied):
    python -m scripts.migrate_database --dry-run

The migration entry point:

* Does NOT connect to any database on import — only when ``main()`` is
  called explicitly.
* Supports both SQLite and PostgreSQL backends.
* Never uses a production Neon URL by default.
* Redacts credentials in all output.
* Returns exit code 0 on success, non-zero on failure.
* Does NOT run automatically on app import (``app.factory.create_app``
  startup still uses the SQLite path).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.config import Settings, redact_database_url
from app.db import apply_migrations, get_connection
from app.db_pg_migrations import (
    PgMigrationError,
    _discover_migrations,
    apply_pg_migrations,
)
from app.db_postgres import PG_MIGRATIONS_DIR, get_pg_connection


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="migrate_database",
        description="Apply database migrations for Personal Edition",
    )
    parser.add_argument(
        "--backend",
        choices=["sqlite", "postgresql"],
        default=None,
        help="Database backend (default: from DB_BACKEND setting, "
        "which defaults to 'sqlite')",
    )
    parser.add_argument(
        "--database",
        default=None,
        help="SQLite database path (default: from DATABASE_PATH setting)",
    )
    parser.add_argument(
        "--url",
        default=None,
        help="PostgreSQL connection URL (default: from PE_DATABASE_URL setting). "
        "For security, use the PE_DATABASE_URL environment variable instead "
        "of passing on the command line.",
    )
    parser.add_argument(
        "--migrations-dir",
        default=None,
        help="Migrations directory (default: app/migrations)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be applied without executing",
    )
    return parser


def _resolve_backend(backend: str | None) -> str:
    if backend is not None:
        return backend
    return Settings().db_backend


def _resolve_url(url: str | None) -> str:
    if url is not None:
        return url
    return Settings().database_url


def _resolve_db_path(db_path: str | None) -> str:
    if db_path is not None:
        return db_path
    return Settings().database_path


def _resolve_migrations_dir(migrations_dir: str | None) -> str:
    if migrations_dir is not None:
        return migrations_dir
    return str(Path(__file__).resolve().parent.parent / "migrations")


def _list_pending_sqlite(migrations_dir: str) -> list[str]:
    """List SQLite migration files (for dry-run)."""
    from app.db import _is_migration_py

    path = Path(migrations_dir)
    sql_files = sorted(
        p for p in path.glob("*.sql")
        if not p.name.startswith("pg_")
    )
    py_files = sorted(
        p for p in path.glob("*.py") if _is_migration_py(p.name)
    )
    all_files = sorted(sql_files + py_files, key=lambda p: p.name)
    return [f.name for f in all_files]


def _list_pending_pg(migrations_dir: str) -> list[str]:
    """List PostgreSQL migration files (for dry-run)."""
    return [m.name for m in _discover_migrations(migrations_dir)]


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    backend = _resolve_backend(args.backend)
    migrations_dir = _resolve_migrations_dir(args.migrations_dir)

    if backend == "postgresql":
        url = _resolve_url(args.url)
        if not url:
            print(
                "ERROR: PostgreSQL backend requires a connection URL.\n"
                "Set PE_DATABASE_URL environment variable or pass --url.\n"
                "Note: the URL is never printed in full — only redacted.",
                file=sys.stderr,
            )
            return 1

        safe_url = redact_database_url(url)
        print(f"Backend: postgresql (url={safe_url})")
        print(f"Migrations dir: {migrations_dir}")

        pending = _list_pending_pg(migrations_dir)
        print(f"Pending migrations: {pending}")

        if args.dry_run:
            print("Dry run — no changes made.")
            return 0

        conn = get_pg_connection(url)
        try:
            applied = apply_pg_migrations(
                conn,
                migrations_dir,
                redact_url=safe_url,
            )
            if applied:
                print(f"Applied: {applied}")
            else:
                print("No new migrations to apply.")
            return 0
        except PgMigrationError as exc:
            print(f"Migration error: {exc}", file=sys.stderr)
            return 1
        finally:
            conn.close()

    else:
        # SQLite backend (default)
        db_path = _resolve_db_path(args.database)
        print(f"Backend: sqlite (path={db_path})")
        print(f"Migrations dir: {migrations_dir}")

        pending = _list_pending_sqlite(migrations_dir)
        print(f"Pending migrations: {pending}")

        if args.dry_run:
            print("Dry run — no changes made.")
            return 0

        conn = get_connection(db_path)
        try:
            applied = apply_migrations(conn, migrations_dir)
            if applied:
                print(f"Applied: {applied}")
            else:
                print("No new migrations to apply.")
            return 0
        except Exception as exc:
            print(f"Migration error: {exc}", file=sys.stderr)
            return 1
        finally:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())
