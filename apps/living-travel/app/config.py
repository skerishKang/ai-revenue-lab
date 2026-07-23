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

    # AI provider configuration
    ai_provider: str = "mock"
    ai_base_url: str = ""
    ai_api_key: str = ""
    ai_model: str = ""
    ai_timeout_seconds: int = 30
    ai_cost_class: str = "free"

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
            elif _gac:
                if not _os.path.isfile(_gac):
                    raise ValueError(
                        "GOOGLE_APPLICATION_CREDENTIALS does not point to a readable file."
                    )
                try:
                    with open(_gac, "rb") as _f:
                        _f.read(1)
                except OSError:
                    raise ValueError(
                        "GOOGLE_APPLICATION_CREDENTIALS does not point to a readable file."
                    )

        if self.allowed_origins:
            from urllib.parse import urlsplit as _urlsplit

            _raw_entries = self.allowed_origins.split(",")
            if any(not _entry.strip() for _entry in _raw_entries):
                raise ValueError(
                    "LT_ALLOWED_ORIGINS must not contain empty entries."
                )

            for _origin in self.allowed_origin_list:
                if "*" in _origin:
                    raise ValueError(
                        "LT_ALLOWED_ORIGINS must not contain wildcard characters."
                    )
                _parts = _urlsplit(_origin)
                if _parts.scheme not in ("http", "https"):
                    raise ValueError(
                        "LT_ALLOWED_ORIGINS entries must use http:// or https:// scheme."
                    )
                if not _parts.hostname:
                    raise ValueError(
                        "LT_ALLOWED_ORIGINS entries must include a hostname."
                    )
                if _parts.username or _parts.password:
                    raise ValueError(
                        "LT_ALLOWED_ORIGINS entries must not contain userinfo."
                    )
                if _parts.path:
                    raise ValueError(
                        "LT_ALLOWED_ORIGINS entries must not contain a path."
                    )
                if _parts.query:
                    raise ValueError(
                        "LT_ALLOWED_ORIGINS entries must not contain a query."
                    )
                if _parts.fragment:
                    raise ValueError(
                        "LT_ALLOWED_ORIGINS entries must not contain a fragment."
                    )
                try:
                    _port = _parts.port
                except ValueError as _exc:
                    raise ValueError(
                        "LT_ALLOWED_ORIGINS entries must not contain an invalid port."
                    ) from _exc
                if _port is not None and not (1 <= _port <= 65535):
                    raise ValueError(
                        "LT_ALLOWED_ORIGINS entries must not contain an invalid port."
                    )

        if self.environment in ("staging", "production") and not self.allowed_origin_list:
            raise ValueError(
                "LT_ALLOWED_ORIGINS must not be empty in staging/production."
            )

        # ------------------------------------------------------------------
        # AI provider validation
        # ------------------------------------------------------------------
        from urllib.parse import urlsplit as _ai_urlsplit

        _VALID_PROVIDERS = {"mock", "openai_compatible"}
        _VALID_COST_CLASSES = {"free", "paid", "local", "unknown"}

        if self.ai_provider not in _VALID_PROVIDERS:
            raise ValueError(
                f"LT_AI_PROVIDER must be one of: {', '.join(sorted(_VALID_PROVIDERS))}. "
                f"Got: '{self.ai_provider}'"
            )

        if self.ai_cost_class not in _VALID_COST_CLASSES:
            raise ValueError(
                f"LT_AI_COST_CLASS must be one of: {', '.join(sorted(_VALID_COST_CLASSES))}. "
                f"Got: '{self.ai_cost_class}'"
            )

        if not (1 <= self.ai_timeout_seconds <= 120):
            raise ValueError(
                "LT_AI_TIMEOUT_SECONDS must be between 1 and 120."
            )

        if self.ai_provider == "openai_compatible":
            _missing: list[str] = []
            if not self.ai_base_url:
                _missing.append("LT_AI_BASE_URL")
            if not self.ai_api_key:
                _missing.append("LT_AI_API_KEY")
            if not self.ai_model:
                _missing.append("LT_AI_MODEL")
            if _missing:
                raise ValueError(
                    "LT_AI_PROVIDER=openai_compatible requires: "
                    + ", ".join(_missing)
                )

            # Validate base URL
            _parts = _ai_urlsplit(self.ai_base_url)
            if _parts.scheme not in ("http", "https"):
                raise ValueError(
                    "LT_AI_BASE_URL must use http:// or https:// scheme."
                )
            if not _parts.hostname:
                raise ValueError(
                    "LT_AI_BASE_URL must include a hostname."
                )
            if _parts.username is not None or _parts.password is not None:
                raise ValueError(
                    "LT_AI_BASE_URL must not contain userinfo."
                )
            if _parts.query:
                raise ValueError(
                    "LT_AI_BASE_URL must not contain a query string."
                )
            if _parts.fragment:
                raise ValueError(
                    "LT_AI_BASE_URL must not contain a fragment."
                )
            try:
                _port = _parts.port
            except ValueError as _exc:
                raise ValueError(
                    "LT_AI_BASE_URL must not contain an invalid port."
                ) from _exc
            if _port is not None and not (1 <= _port <= 65535):
                raise ValueError(
                    "LT_AI_BASE_URL must not contain a valid port (1-65535)."
                )

            if self.environment in ("staging", "production"):
                if _parts.scheme != "https":
                    raise ValueError(
                        "LT_AI_BASE_URL must use https:// in staging/production."
                    )
                _host = (_parts.hostname or "").lower()
                if _host in (
                    "localhost",
                    "127.0.0.1",
                    "::1",
                    "0.0.0.0",
                ) or _host.startswith(("169.254.", "10.", "172.16.", "192.168.")):
                    raise ValueError(
                        "LT_AI_BASE_URL must not point to a localhost, loopback, "
                        "or private network address in staging/production."
                    )
            elif self.environment == "development" and _parts.scheme == "http":
                _host = (_parts.hostname or "").lower()
                if _host not in ("localhost", "127.0.0.1", "::1"):
                    raise ValueError(
                        "HTTP LT_AI_BASE_URL in development is only allowed "
                        "for localhost or loopback addresses."
                    )

    @property
    def allowed_origin_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def ai_chat_completions_url(self) -> str:
        """Normalize base URL and append /v1/chat/completions safely."""
        base = self.ai_base_url.rstrip("/")
        if "/v1" not in base:
            base = base.rstrip("/") + "/v1"
        return base.rstrip("/") + "/chat/completions"

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
