"""Production configuration fail-closed contracts."""

from __future__ import annotations

import pytest

from app.config import Settings


def test_default_is_sqlite_mock():
    s = Settings(database_url=":memory:")
    assert s.database_backend == "sqlite"
    assert s.provider_type == "mock"
    assert s.deployment_environment == "development"


def test_invalid_backend_rejected():
    with pytest.raises(ValueError):
        Settings(database_backend="mysql", database_url=":memory:")


def test_postgres_requires_postgres_url():
    with pytest.raises(ValueError):
        Settings(database_backend="postgresql", database_url=":memory:")


def test_postgres_requires_migration_url():
    with pytest.raises(ValueError):
        Settings(
            database_backend="postgresql",
            database_url="postgresql://u:p@host/db",
            migration_database_url="",
        )


def test_postgres_migration_url_must_be_postgres():
    with pytest.raises(ValueError):
        Settings(
            database_backend="postgresql",
            database_url="postgresql://u:p@host/db",
            migration_database_url="sqlite:///x.db",
        )


def test_postgres_valid_config_accepted():
    s = Settings(
        database_backend="postgresql",
        database_url="postgresql://u:p@host/db",
        migration_database_url="postgresql://owner:p@host/db",
    )
    assert s.effective_migration_url == "postgresql://owner:p@host/db"


def test_sqlite_does_not_absolutize_postgres_url():
    s = Settings(
        database_backend="postgresql",
        database_url="postgresql://u:p@host/db",
        migration_database_url="postgresql://owner:p@host/db",
    )
    assert s.database_url == "postgresql://u:p@host/db"


def test_mock_provider_rejected_in_production_without_allow():
    with pytest.raises(ValueError):
        Settings(environment="production", provider_type="mock", allow_mock_staging=False)


def test_mock_provider_allowed_in_staging_with_flag():
    s = Settings(environment="staging", provider_type="mock", allow_mock_staging=True, allowed_origins="https://x.example")
    assert s.provider_type == "mock"


def test_firebase_requires_project_id():
    with pytest.raises(ValueError):
        Settings(identity_provider="firebase", firebase_project_id="", environment="staging")


def test_invalid_identity_provider_rejected():
    with pytest.raises(ValueError):
        Settings(identity_provider="okta")


def test_wildcard_origin_rejected():
    with pytest.raises(ValueError):
        Settings(environment="staging", allowed_origins="*")


def test_non_http_origin_rejected():
    with pytest.raises(ValueError):
        Settings(environment="staging", allowed_origins="ftp://x.example")


def test_staging_requires_origins():
    with pytest.raises(ValueError):
        Settings(environment="staging", allowed_origins="")


def test_valid_origins_accepted():
    s = Settings(environment="staging", allowed_origins="https://a.example, https://b.example")
    assert s.allowed_origin_list == ["https://a.example", "https://b.example"]
