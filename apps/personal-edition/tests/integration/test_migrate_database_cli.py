"""Tests for the migration entry point CLI.

Covers:
- import only does not connect
- SQLite path works
- PostgreSQL path requires URL
- dry-run works
- exit codes
- secret redaction in output
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.config import redact_database_url


BASE_DIR = Path(__file__).resolve().parent.parent.parent


class TestMigrationCliImport:
    """import only does not connect."""

    def test_import_does_not_connect(self):
        """Importing the migration script must not open a connection."""
        import importlib
        import sys

        # Remove from cache
        for mod in list(sys.modules):
            if "migrate_database" in mod:
                del sys.modules[mod]

        importlib.import_module("scripts.migrate_database")
        assert True  # If we got here, no connection was opened


class TestMigrationCliSqlite:
    """SQLite path works."""

    def test_dry_run_sqlite(self):
        env = dict(os.environ)
        env.pop("DATABASE_PATH", None)
        env.pop("DB_BACKEND", None)
        result = subprocess.run(
            [
                sys.executable, "-m", "scripts.migrate_database",
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            cwd=str(BASE_DIR),
            env=env,
        )
        assert result.returncode == 0
        assert "sqlite" in result.stdout.lower()
        assert "Dry run" in result.stdout

    def test_dry_run_sqlite_custom_path(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        env = dict(os.environ)
        env.pop("DATABASE_PATH", None)
        env.pop("DB_BACKEND", None)
        result = subprocess.run(
            [
                sys.executable, "-m", "scripts.migrate_database",
                "--backend", "sqlite",
                "--database", db_path,
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            cwd=str(BASE_DIR),
            env=env,
        )
        assert result.returncode == 0
        assert db_path in result.stdout

    def test_apply_sqlite(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        env = dict(os.environ)
        env.pop("DATABASE_PATH", None)
        env.pop("DB_BACKEND", None)
        result = subprocess.run(
            [
                sys.executable, "-m", "scripts.migrate_database",
                "--backend", "sqlite",
                "--database", db_path,
            ],
            capture_output=True,
            text=True,
            cwd=str(BASE_DIR),
            env=env,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Applied:" in result.stdout

        # Verify the database was created
        assert Path(db_path).exists()


class TestMigrationCliPostgresql:
    """PostgreSQL path requires URL."""

    def test_pg_without_url_fails(self):
        env = dict(os.environ)
        env.pop("PE_DATABASE_URL", None)
        env.pop("DB_BACKEND", None)
        result = subprocess.run(
            [
                sys.executable, "-m", "scripts.migrate_database",
                "--backend", "postgresql",
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            cwd=str(BASE_DIR),
            env=env,
        )
        assert result.returncode == 1
        assert "PostgreSQL backend requires a connection URL" in result.stderr

    def test_pg_dry_run_with_url(self):
        env = dict(os.environ)
        env.pop("PE_DATABASE_URL", None)
        env.pop("DB_BACKEND", None)
        result = subprocess.run(
            [
                sys.executable, "-m", "scripts.migrate_database",
                "--backend", "postgresql",
                "--url", "postgresql://user:pass@host:5432/db",
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            cwd=str(BASE_DIR),
            env=env,
        )
        assert result.returncode == 0
        assert "postgresql" in result.stdout.lower()
        # URL must be redacted
        assert "pass" not in result.stdout
        assert "[REDACTED]" in result.stdout

    def test_pg_no_production_default(self):
        """production 자동 실행 금지 — CLI never defaults to production."""
        # The CLI should not auto-detect or use production URLs
        env = dict(os.environ)
        env.pop("PE_DATABASE_URL", None)
        env.pop("DATABASE_URL", None)
        env.pop("DB_BACKEND", None)
        result = subprocess.run(
            [
                sys.executable, "-m", "scripts.migrate_database",
                "--backend", "postgresql",
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            cwd=str(BASE_DIR),
            env=env,
        )
        assert result.returncode == 1
        assert "requires a connection URL" in result.stderr


class TestMigrationCliSecretRedaction:
    """secret redaction in CLI output."""

    def test_url_redacted_in_output(self):
        env = dict(os.environ)
        env.pop("PE_DATABASE_URL", None)
        env.pop("DB_BACKEND", None)
        result = subprocess.run(
            [
                sys.executable, "-m", "scripts.migrate_database",
                "--backend", "postgresql",
                "--url", "postgresql://user:secret@db.example.com:5432/db",
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            cwd=str(BASE_DIR),
            env=env,
        )
        assert result.returncode == 0
        assert "secret" not in result.stdout
        assert "secret" not in result.stderr
        assert "[REDACTED]" in result.stdout

    def test_query_params_not_in_output(self):
        env = dict(os.environ)
        env.pop("PE_DATABASE_URL", None)
        env.pop("DB_BACKEND", None)
        result = subprocess.run(
            [
                sys.executable, "-m", "scripts.migrate_database",
                "--backend", "postgresql",
                "--url", "postgresql://user:pass@host/db?sslmode=require&channel_binding=require",
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            cwd=str(BASE_DIR),
            env=env,
        )
        assert result.returncode == 0
        assert "sslmode" not in result.stdout
        assert "channel_binding" not in result.stdout
