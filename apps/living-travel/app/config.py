"""Application configuration with environment-backed settings."""

import json as _json
import os as _os

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
            _sa_json = _os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON", "")
            _gac = _os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
            if not _sa_json and not _gac:
                raise ValueError(
                    "LT_AUTH_MODE=firebase in non-testing environments requires "
                    "FIREBASE_SERVICE_ACCOUNT_JSON or GOOGLE_APPLICATION_CREDENTIALS."
                )
            if _sa_json:
                try:
                    _parsed = _json.loads(_sa_json)
                except (ValueError, _json.JSONDecodeError) as _exc:
                    raise ValueError(
                        "FIREBASE_SERVICE_ACCOUNT_JSON is not valid JSON."
                    ) from _exc
                if not isinstance(_parsed, dict):
                    raise ValueError(
                        "FIREBASE_SERVICE_ACCOUNT_JSON must be a JSON object."
                    )
                _required = {"type", "project_id", "private_key", "client_email"}
                if not _required.issubset(_parsed.keys()):
                    raise ValueError(
                        "FIREBASE_SERVICE_ACCOUNT_JSON is missing required fields."
                    )
            elif _gac and not _os.path.isfile(_gac):
                raise ValueError(
                    "GOOGLE_APPLICATION_CREDENTIALS does not point to a readable file."
                )

        if self.allowed_origins:
            from urllib.parse import urlparse as _urlparse

            for _origin in self.allowed_origin_list:
                if "*" in _origin:
                    raise ValueError(
                        "LT_ALLOWED_ORIGINS must not contain wildcard characters."
                    )
                if not _origin.startswith(("http://", "https://")):
                    raise ValueError(
                        "LT_ALLOWED_ORIGINS entries must use http:// or https:// scheme."
                    )
                _parsed_origin = _urlparse(_origin)
                if _parsed_origin.path and _parsed_origin.path not in ("", "/"):
                    raise ValueError(
                        "LT_ALLOWED_ORIGINS entries must not contain a path."
                    )
                if _parsed_origin.query or _parsed_origin.fragment:
                    raise ValueError(
                        "LT_ALLOWED_ORIGINS entries must not contain query or fragment."
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
