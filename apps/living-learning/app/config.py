"""Application configuration with environment-backed settings.

Environment contract (all ``LL_`` prefixed):

    LL_DATABASE_BACKEND=sqlite|postgresql
    LL_DATABASE_URL=            sqlite path, OR runtime pooled PostgreSQL URL
    LL_MIGRATION_DATABASE_URL=  migration-owner direct PostgreSQL URL
    LL_PROVIDER_TYPE=mock|<configured-live-provider>
    LL_PROVIDER_MODEL=<advertised model>
    LL_ALLOW_MOCK_STAGING=true|false
    LL_IDENTITY_PROVIDER=fake|firebase
    LL_FIREBASE_PROJECT_ID=<firebase project>
    LL_ENVIRONMENT=development|staging|production
    LL_ALLOWED_ORIGINS=<comma-separated exact origins>

Fail-closed: backend selection is explicit (never inferred from the URL), a
PostgreSQL backend refuses to silently fall back to SQLite, and staging/
production enforce origins and mock-staging policy. Error messages are generic
and never include URLs or secrets.
"""

import os
from pathlib import Path
from pydantic_settings import BaseSettings

_PLACEHOLDER_SECRETS = {"changeme", "change-me", "secret", "password", ""}


def _is_postgres_url(url: str) -> bool:
    u = (url or "").strip().lower()
    return u.startswith("postgresql://") or u.startswith("postgres://")


class Settings(BaseSettings):
    app_name: str = "living-learning"
    # Database backend selection (explicit; never inferred from the URL).
    database_backend: str = "sqlite"
    # sqlite path OR runtime pooled PostgreSQL URL (treated as secret).
    database_url: str = "var/living-learning.db"
    # Migration-owner direct PostgreSQL URL (secret; not used at runtime).
    migration_database_url: str = ""
    environment: str = "development"
    # Provider staging contract.
    provider_model: str = "mock/mock-fixture"
    provider_type: str = "mock"
    allow_mock_staging: bool = False
    # Portal-ready boundary configuration.
    identity_provider: str = "fake"
    firebase_project_id: str = ""
    # Comma-separated exact origins. Empty => no CORS middleware (fail-closed).
    allowed_origins: str = ""

    model_config = {"env_prefix": "LL_", "env_file": ".env", "extra": "ignore"}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Only treat database_url as a filesystem path for the sqlite backend;
        # for postgresql it is a connection URL and must not be path-absolutized.
        if self.database_backend == "sqlite":
            if self.database_url and not self.database_url.startswith(":"):
                db_path = Path(self.database_url)
                if not db_path.is_absolute():
                    base_dir = Path(__file__).resolve().parent.parent.parent
                    self.database_url = str(base_dir / db_path)
        self._validate()

    def _validate(self) -> None:
        backend = (self.database_backend or "").strip().lower()
        if backend not in ("sqlite", "postgresql"):
            raise ValueError("LL_DATABASE_BACKEND must be 'sqlite' or 'postgresql'")
        self.database_backend = backend

        if backend == "postgresql":
            if not _is_postgres_url(self.database_url):
                raise ValueError(
                    "LL_DATABASE_BACKEND=postgresql requires a postgresql:// "
                    "LL_DATABASE_URL. Refusing to silently fall back to SQLite."
                )
            if not self.migration_database_url.strip():
                raise ValueError(
                    "LL_DATABASE_BACKEND=postgresql requires LL_MIGRATION_DATABASE_URL "
                    "(direct, non-pooled connection). Refusing to fall back to the runtime URL."
                )
            if not _is_postgres_url(self.migration_database_url):
                raise ValueError(
                    "LL_MIGRATION_DATABASE_URL must be a postgresql:// connection URL."
                )

        if self.identity_provider not in ("fake", "firebase"):
            raise ValueError("LL_IDENTITY_PROVIDER must be 'fake' or 'firebase'")

        if self.identity_provider == "firebase" and self.environment != "testing":
            if not self.firebase_project_id.strip():
                raise ValueError(
                    "LL_IDENTITY_PROVIDER=firebase requires LL_FIREBASE_PROJECT_ID."
                )

        # Mock staging policy: a mock provider may serve staging only when
        # explicitly allowed; it is never a live production provider.
        if self.provider_type == "mock" and self.environment == "production" and not self.allow_mock_staging:
            raise ValueError(
                "LL_PROVIDER_TYPE=mock is not a production provider. Set a configured "
                "live provider, or LL_ALLOW_MOCK_STAGING=true for synthetic staging only."
            )

        self._validate_allowed_origins()

    def _validate_allowed_origins(self) -> None:
        origins = self.allowed_origin_list
        if not origins:
            if self.environment in ("staging", "production"):
                raise ValueError(
                    "LL_ALLOWED_ORIGINS must be a non-empty exact-origin list in "
                    "staging/production."
                )
            return
        for origin in origins:
            if "*" in origin:
                raise ValueError("LL_ALLOWED_ORIGINS must not contain wildcards.")
            if not (origin.startswith("http://") or origin.startswith("https://")):
                raise ValueError("LL_ALLOWED_ORIGINS entries must be http(s) origins.")

    @property
    def allowed_origin_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def effective_migration_url(self) -> str:
        """Direct (unpooled) URL for migrations. No fallback for PostgreSQL."""
        if self.database_backend == "postgresql":
            return self.migration_database_url
        return self.migration_database_url or self.database_url

    @property
    def deployment_environment(self) -> str:
        return self.environment


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    global _settings
    _settings = None
