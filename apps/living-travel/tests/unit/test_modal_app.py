"""Modal staging app smoke tests and fail-closed configuration tests.

These run offline: importing modal_app only defines the App/image/function
(no network, no deploy). Live Modal deployment is verified separately.
"""

from __future__ import annotations

import pytest


class TestModalAppImport:
    def test_import_and_names(self):
        pytest.importorskip("modal")
        import modal_app

        assert modal_app.APP_NAME == "ai-revenue-living-travel-staging"
        assert modal_app.SECRET_NAME == "ai-revenue-living-travel-staging"
        assert modal_app.app is not None
        assert modal_app.web is not None

    def test_no_sqlite_volume_in_image(self):
        pytest.importorskip("modal")
        import inspect

        import modal_app

        src = inspect.getsource(modal_app)
        assert "modal.Volume" not in src
        # No actual SQLite driver/database usage (docstring mentions are fine).
        assert "sqlite3" not in src


class TestFailClosedConfig:
    def test_postgresql_without_url_fails(self):
        from app.config import Settings

        with pytest.raises(Exception) as exc:
            Settings(
                database_backend="postgresql",
                database_url="file::memory:",
                environment="testing",
            )
        assert "postgresql" in str(exc.value).lower()

    def test_firebase_without_project_id_fails(self):
        from app.config import Settings

        with pytest.raises(Exception) as exc:
            Settings(
                auth_mode="firebase",
                environment="staging",
                firebase_project_id="",
            )
        assert "firebase" in str(exc.value).lower()

    def test_invalid_backend_fails(self):
        from app.config import Settings

        with pytest.raises(Exception):
            Settings(database_backend="mysql", environment="testing")

    def test_valid_sqlite_legacy_ok(self):
        from app.config import Settings

        s = Settings(environment="testing")
        assert s.database_backend == "sqlite"
        assert s.auth_mode == "legacy"


class TestMigrationUrlFailClosed:
    def test_postgresql_missing_migration_url_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError) as exc:
            Settings(
                database_backend="postgresql",
                database_url="postgresql://user:pass@host/db",
                migration_database_url="",
                environment="testing",
            )
        assert "LT_MIGRATION_DATABASE_URL" in str(exc.value)
        assert "postgresql://user:pass@host/db" not in str(exc.value)

    def test_postgresql_empty_migration_url_fails(self):
        from app.config import Settings

        with pytest.raises(ValueError) as exc:
            Settings(
                database_backend="postgresql",
                database_url="postgresql://u:p@h/d",
                migration_database_url="",
                environment="testing",
            )
        assert "LT_MIGRATION_DATABASE_URL" in str(exc.value)

    def test_postgresql_invalid_scheme_migration_url_fails(self):
        from app.config import Settings

        for bad_url in ("sqlite:///tmp/x.db", "file::memory:", "http://example.com"):
            with pytest.raises(ValueError) as exc:
                Settings(
                    database_backend="postgresql",
                    database_url="postgresql://u:p@h/d",
                    migration_database_url=bad_url,
                    environment="testing",
                )
            assert "scheme" in str(exc.value).lower()

    def test_postgresql_valid_migration_url_passes(self):
        from app.config import Settings

        s = Settings(
            database_backend="postgresql",
            database_url="postgresql://u:p@pooled.host/db",
            migration_database_url="postgresql://u:p@direct.host/db",
            environment="testing",
        )
        assert s.effective_migration_url == "postgresql://u:p@direct.host/db"

    def test_postgres_scheme_also_accepted(self):
        from app.config import Settings

        s = Settings(
            database_backend="postgresql",
            database_url="postgres://u:p@pooled.host/db",
            migration_database_url="postgres://u:p@direct.host/db",
            environment="testing",
        )
        assert s.effective_migration_url == "postgres://u:p@direct.host/db"

    def test_sqlite_no_migration_url_ok(self):
        from app.config import Settings

        s = Settings(
            database_backend="sqlite",
            database_url="file::memory:",
            migration_database_url="",
            environment="testing",
        )
        assert s.effective_migration_url == "file::memory:"

    def test_sqlite_explicit_migration_url_used(self):
        from app.config import Settings

        s = Settings(
            database_backend="sqlite",
            database_url="file::memory:",
            migration_database_url="/tmp/other.db",
            environment="testing",
        )
        assert s.effective_migration_url == "/tmp/other.db"

    def test_error_message_no_url_leak(self):
        from app.config import Settings

        secret_url = "postgresql://admin:s3cr3t-pw@neon.host/prod_db"
        with pytest.raises(ValueError) as exc:
            Settings(
                database_backend="postgresql",
                database_url=secret_url,
                migration_database_url="",
                environment="testing",
            )
        error_text = str(exc.value)
        assert "s3cr3t-pw" not in error_text.split("input_type")[0]
