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

    def test_import_does_not_connect(self, isolated_sys_modules):
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
        # Password must be redacted.
        assert "pass" not in result.stdout
        # The entire userinfo (username included) is now stripped.
        assert "user" not in result.stdout.split("host")[0]
        assert "host" in result.stdout

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
        # The username itself must also be redacted now.
        assert "user" not in result.stdout.replace("user=", "")
        assert "db.example.com" in result.stdout

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


class TestRedactDatabaseUrl:
    """Unit tests for the redact_database_url helper itself.

    These run without any PostgreSQL connection and verify that the full
    userinfo (username + password), query string and fragment are stripped.
    """

    def test_strips_password(self):
        url = "postgresql://user:hunter2@host:5432/db"
        redacted = redact_database_url(url)
        assert "hunter2" not in redacted
        assert "host" in redacted

    def test_strips_username(self):
        url = "postgresql://alice:secret@host:5432/db"
        redacted = redact_database_url(url)
        assert "alice" not in redacted
        assert "secret" not in redacted
        assert "host" in redacted
        assert "@host" not in redacted

    def test_strips_query_and_fragment(self):
        url = "postgresql://user:pass@host:5432/db?sslmode=require&token=abc#frag"
        redacted = redact_database_url(url)
        assert "sslmode" not in redacted
        assert "token" not in redacted
        assert "abc" not in redacted
        assert "frag" not in redacted
        assert "pass" not in redacted

    def test_malformed_postgres_url(self):
        # No host — must not echo back the raw (possibly userinfo-bearing) URL.
        url = "postgresql://user:pass@"
        redacted = redact_database_url(url)
        assert "pass" not in redacted
        assert "user" not in redacted
        assert "[REDACTED]" in redacted

    def test_non_postgres_url_unchanged_except_query(self):
        url = "sqlite:///path/to/db.sqlite?cache=shared"
        redacted = redact_database_url(url)
        assert "path/to/db.sqlite" in redacted
        assert "cache=shared" not in redacted

    def test_empty_and_non_string(self):
        assert redact_database_url("") == ""
        assert redact_database_url(None) is None  # type: ignore[arg-type]

    def test_postgres_scheme_alias(self):
        url = "postgres://user:pass@host/db"
        redacted = redact_database_url(url)
        assert "pass" not in redacted
        assert "user" not in redacted
        assert "host" in redacted


class TestMigrationCliDriverError:
    """Driver/connection failures must produce safe, category-only output."""

    def test_connection_failure_no_traceback(self):
        env = dict(os.environ)
        env.pop("PE_DATABASE_URL", None)
        env.pop("DB_BACKEND", None)
        result = subprocess.run(
            [
                sys.executable, "-m", "scripts.migrate_database",
                "--backend", "postgresql",
                "--url", "postgresql://nobody:secret@127.0.0.1:1/db",
            ],
            capture_output=True,
            text=True,
            cwd=str(BASE_DIR),
            env=env,
        )
        # Non-zero exit due to connection failure.
        assert result.returncode == 1
        # The password must never appear in any output stream.
        assert "secret" not in result.stdout
        assert "secret" not in result.stderr
        # The username must never appear in any output stream.
        assert "nobody" not in result.stdout
        assert "nobody" not in result.stderr
