"""Tests for the database backend selection contract.

Covers:
- backend 미설정 시 SQLite (local/test default)
- 명시적 SQLite 선택
- 명시적 PostgreSQL 선택
- invalid backend 실패
- PostgreSQL URL 누락 실패
- SQLite/PostgreSQL 설정 혼합 방지
- production misconfiguration fail closed
"""

import pytest

from app.config import (
    Settings,
    _POSTGRES_URL_RE,
    redact_database_url,
)


class TestBackendDefaults:
    """local/test에서는 backend 미설정 시 SQLite가 기본."""

    def test_default_backend_is_sqlite(self):
        s = Settings()
        assert s.db_backend == "sqlite"

    def test_default_database_path(self):
        s = Settings()
        assert s.database_path == "var/personal-edition.db"

    def test_default_database_url_is_empty(self):
        s = Settings()
        assert s.database_url == ""


class TestExplicitSqlite:
    """명시적 SQLite 선택."""

    def test_explicit_sqlite(self):
        s = Settings(db_backend="sqlite")
        assert s.db_backend == "sqlite"

    def test_explicit_sqlite_with_custom_path(self):
        s = Settings(db_backend="sqlite", database_path="/tmp/test.db")
        assert s.db_backend == "sqlite"
        assert s.database_path == "/tmp/test.db"


class TestExplicitPostgresql:
    """명시적 PostgreSQL 선택."""

    def test_explicit_postgresql_with_url(self):
        s = Settings(
            db_backend="postgresql",
            PE_DATABASE_URL="postgresql://user:pass@host:5432/db",
        )
        assert s.db_backend == "postgresql"
        assert s.database_url == "postgresql://user:pass@host:5432/db"

    def test_explicit_postgresql_with_postgres_scheme(self):
        s = Settings(
            db_backend="postgresql",
            PE_DATABASE_URL="postgres://user:pass@host:5432/db",
        )
        assert s.db_backend == "postgresql"

    def test_explicit_postgresql_with_localhost(self):
        s = Settings(
            db_backend="postgresql",
            PE_DATABASE_URL="postgresql://user:pass@localhost:5432/db",
        )
        assert s.db_backend == "postgresql"


class TestInvalidBackend:
    """invalid backend 실패."""

    def test_invalid_backend_mysql(self):
        with pytest.raises(ValueError, match="DB_BACKEND"):
            Settings(db_backend="mysql")

    def test_invalid_backend_mongodb(self):
        with pytest.raises(ValueError, match="DB_BACKEND"):
            Settings(db_backend="mongodb")

    def test_invalid_backend_empty(self):
        with pytest.raises(ValueError, match="DB_BACKEND"):
            Settings(db_backend="")


class TestPostgresqlUrlRequired:
    """PostgreSQL URL 누락 실패."""

    def test_postgresql_without_url_fails(self):
        with pytest.raises(ValueError, match="DATABASE_URL is required"):
            Settings(db_backend="postgresql")

    def test_postgresql_with_empty_url_fails(self):
        with pytest.raises(ValueError, match="DATABASE_URL is required"):
            Settings(
                db_backend="postgresql",
                PE_DATABASE_URL="",
            )

    def test_postgresql_with_invalid_url_fails(self):
        with pytest.raises(ValueError, match="valid PostgreSQL"):
            Settings(
                db_backend="postgresql",
                PE_DATABASE_URL="not-a-url",
            )

    def test_postgresql_with_sqlite_path_fails(self):
        with pytest.raises(ValueError, match="valid PostgreSQL"):
            Settings(
                db_backend="postgresql",
                PE_DATABASE_URL="var/personal-edition.db",
            )


class TestMixedConfigPrevented:
    """SQLite/PostgreSQL 설정 혼합 방지."""

    def test_sqlite_with_database_url_fails(self):
        with pytest.raises(ValueError, match="must not be set"):
            Settings(
                db_backend="sqlite",
                PE_DATABASE_URL="postgresql://user:pass@host/db",
            )

    def test_sqlite_with_database_url_and_custom_path_fails(self):
        with pytest.raises(ValueError, match="must not be set"):
            Settings(
                db_backend="sqlite",
                database_path="/tmp/test.db",
                PE_DATABASE_URL="postgresql://user:pass@host/db",
            )


class TestProductionFailClosed:
    """production misconfiguration fail closed."""

    def _prod_kwargs(self, **overrides):
        kwargs = dict(
            app_env="production",
            secret_key="a-very-strong-secret-key-at-least-32-chars!",
            admin_secret="a-strong-admin-secret-here!",
            cookie_secure=True,
        )
        kwargs.update(overrides)
        return kwargs

    def test_production_default_sqlite_path_fails(self):
        """production에서 backend 미설정 시 SQLite로 가면 안 됨."""
        with pytest.raises(ValueError, match="DATABASE_PATH must be explicitly"):
            Settings(**self._prod_kwargs())

    def test_production_sqlite_with_explicit_path_ok(self):
        s = Settings(
            **self._prod_kwargs(
                db_backend="sqlite",
                database_path="/data/personal-edition.db",
            )
        )
        assert s.db_backend == "sqlite"
        assert s.database_path == "/data/personal-edition.db"

    def test_production_postgresql_without_url_fails(self):
        with pytest.raises(ValueError, match="DATABASE_URL is required"):
            Settings(**self._prod_kwargs(db_backend="postgresql"))

    def test_production_postgresql_with_url_ok(self):
        s = Settings(
            **self._prod_kwargs(
                db_backend="postgresql",
                PE_DATABASE_URL="postgresql://user:pass@host:5432/db",
            )
        )
        assert s.db_backend == "postgresql"

    def test_production_sqlite_with_pg_url_fails(self):
        with pytest.raises(ValueError, match="must not be set"):
            Settings(
                **self._prod_kwargs(
                    db_backend="sqlite",
                    database_path="/data/personal-edition.db",
                    PE_DATABASE_URL="postgresql://user:pass@host/db",
                )
            )


class TestUrlRegex:
    """PostgreSQL URL regex validation."""

    def test_valid_postgresql_url(self):
        assert _POSTGRES_URL_RE.match(
            "postgresql://user:pass@host:5432/db"
        )

    def test_valid_postgres_scheme(self):
        assert _POSTGRES_URL_RE.match(
            "postgres://user:pass@host:5432/db"
        )

    def test_valid_no_password(self):
        assert _POSTGRES_URL_RE.match(
            "postgresql://user@host:5432/db"
        )

    def test_valid_no_userinfo(self):
        assert _POSTGRES_URL_RE.match(
            "postgresql://host:5432/db"
        )

    def test_invalid_plain_string(self):
        assert not _POSTGRES_URL_RE.match("not-a-url")

    def test_invalid_sqlite_path(self):
        assert not _POSTGRES_URL_RE.match("var/personal-edition.db")


class TestRedactDatabaseUrl:
    """password redaction."""

    def test_redacts_password(self):
        url = "postgresql://user:secret@db.example.com:5432/mydb"
        redacted = redact_database_url(url)
        assert "secret" not in redacted
        assert "[REDACTED]" in redacted

    def test_redacts_password_with_query_params(self):
        url = "postgresql://user:secret@db.example.com:5432/mydb?sslmode=require"
        redacted = redact_database_url(url)
        assert "secret" not in redacted
        assert "?" not in redacted

    def test_redacts_empty_username_password(self):
        url = "postgresql://:pass@db.example.com/mydb"
        redacted = redact_database_url(url)
        assert "pass" not in redacted

    def test_no_password_no_redaction_needed(self):
        url = "postgresql://user@db.example.com:5432/mydb"
        redacted = redact_database_url(url)
        # user is shown but no password to redact
        assert "user" in redacted

    def test_no_userinfo(self):
        url = "postgresql://host/db"
        redacted = redact_database_url(url)
        assert redacted == "postgresql://host/db"

    def test_sqlite_path_unchanged(self):
        url = "var/personal-edition.db"
        redacted = redact_database_url(url)
        assert redacted == "var/personal-edition.db"

    def test_empty_string(self):
        assert redact_database_url("") == ""

    def test_query_parameter_redaction(self):
        """query parameter redaction."""
        url = "postgresql://user:pass@host/db?sslmode=require&channel_binding=require"
        redacted = redact_database_url(url)
        assert "?" not in redacted
        assert "sslmode" not in redacted
        assert "channel_binding" not in redacted

    def test_exception_output_no_secret(self):
        """exception 출력에 secret 없음."""
        url = "postgresql://user:secret@db.example.com/db"
        redacted = redact_database_url(url)
        # Simulate error message
        error_msg = f"Connection failed (url={redacted})"
        assert "secret" not in error_msg
        assert "password" not in error_msg.lower() or "[REDACTED]" in error_msg

    def test_config_repr_no_url(self):
        """config repr 또는 로그에 URL 전체 없음."""
        s = Settings(
            db_backend="postgresql",
            PE_DATABASE_URL="postgresql://user:secret@host/db",
        )
        repr_str = repr(s)
        # The raw password must not appear in repr
        assert "postgresql://user:secret" not in repr_str
        assert ":secret@" not in repr_str
        # The redacted version should be present
        assert "[REDACTED]" in repr_str
