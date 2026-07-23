"""Application configuration with environment-backed settings."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "living-travel"
    database_url: str = "file::memory:"
    environment: str = "development"
    operator_secret: str = "changeme"

    database_backend: str = "sqlite"
    migration_database_url: str = ""
    auth_mode: str = "legacy"
    firebase_project_id: str = ""
    allowed_origins: str = ""

    model_config = {"env_prefix": "LT_", "env_file": ".env", "extra": "ignore"}

    def model_post_init(self, __context) -> None:
        """Validate secrets and backend/auth configuration (fail-closed)."""
        _PLACEHOLDERS = {"changeme", "change-me", "secret", "password", ""}
        if self.environment != "testing" and self.auth_mode == "legacy":
            if not self.operator_secret or self.operator_secret.lower() in _PLACEHOLDERS:
                raise ValueError(
                    "LT_OPERATOR_SECRET must be set to a secure value. "
                    "The default placeholder is not allowed in non-testing environments."
                )
            if len(self.operator_secret) < 16:
                raise ValueError(
                    "LT_OPERATOR_SECRET must be at least 16 characters."
                )

        if self.database_backend not in ("sqlite", "postgresql"):
            raise ValueError("LT_DATABASE_BACKEND must be 'sqlite' or 'postgresql'")
        if self.auth_mode not in ("legacy", "firebase"):
            raise ValueError("LT_AUTH_MODE must be 'legacy' or 'firebase'")

        if self.database_backend == "postgresql":
            if not (
                self.database_url.startswith("postgresql://")
                or self.database_url.startswith("postgres://")
            ):
                raise ValueError(
                    "LT_DATABASE_BACKEND=postgresql requires a postgresql:// "
                    "LT_DATABASE_URL. Refusing to silently fall back to SQLite."
                )
            if not self.migration_database_url:
                raise ValueError(
                    "LT_DATABASE_BACKEND=postgresql requires "
                    "LT_MIGRATION_DATABASE_URL (direct, non-pooled connection). "
                    "Refusing to fall back to the runtime URL."
                )
            if not (
                self.migration_database_url.startswith("postgresql://")
                or self.migration_database_url.startswith("postgres://")
            ):
                raise ValueError(
                    "LT_MIGRATION_DATABASE_URL must use a postgresql:// or "
                    "postgres:// scheme."
                )

        if self.auth_mode == "firebase" and self.environment != "testing":
            if not self.firebase_project_id:
                raise ValueError(
                    "LT_AUTH_MODE=firebase requires LT_FIREBASE_PROJECT_ID."
                )

    @property
    def allowed_origin_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def effective_migration_url(self) -> str:
        """Direct (unpooled) URL for migrations. No fallback for PostgreSQL."""
        if self.database_backend == "postgresql":
            return self.migration_database_url
        return self.migration_database_url or self.database_url


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    global _settings
    _settings = None
