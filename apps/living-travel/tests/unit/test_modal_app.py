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
