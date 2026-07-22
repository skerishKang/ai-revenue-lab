import re
from urllib.parse import urlparse, urlunparse

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings

_DEFAULT_SECRETS = frozenset({
    "dev-secret-key-change-in-production",
    "dev-admin-secret-change-in-production",
})

_VALID_PROVIDERS = frozenset({"mock", "external"})
_VALID_COST_CLASSES = frozenset({"free", "paid", "local", "unknown"})
_VALID_RESPONSE_FORMAT_MODES = frozenset({"json_schema", "json_object"})

_VALID_DB_BACKENDS = frozenset({"sqlite", "postgresql"})

# Matches postgresql:// or postgres:// with optional user[:password]@host
_POSTGRES_URL_RE = re.compile(
    r"^postgres(?:ql)?://"
    r"(?:(?P<user>[^:/@]+)(?::(?P<pass>[^/@]*))?@)?"
    r"(?P<host>[^:/@]+)"
    r"(?::(?P<port>\d+))?"
    r"(?P<path>/[^\s]*)?$",
    re.IGNORECASE,
)

def redact_database_url(url: str) -> str:
    """Redact all userinfo from a PostgreSQL connection URL.

    The entire userinfo component (username **and** password) is removed, and
    any query string and fragment are dropped entirely — query parameters may
    contain additional secrets such as ``sslmode`` with credentials or
    provider-specific auth options.  Only the scheme, host, port and path are
    preserved.

    A malformed postgres URL (no parseable host) is reduced to a fixed
    placeholder so that no partial userinfo can leak.

    For non-postgres URLs (e.g. SQLite paths) the query string is stripped as
    a best-effort and the rest is returned unchanged.
    """
    if not isinstance(url, str) or not url:
        return url
    try:
        parsed = urlparse(url)
    except Exception:
        return url.split("?", 1)[0]

    scheme = (parsed.scheme or "").lower()
    if scheme not in ("postgresql", "postgres"):
        # Not a postgres URL (e.g. SQLite path) — no userinfo to redact.
        return url.split("?", 1)[0]

    host = parsed.hostname
    if not host:
        # Malformed postgres URL — never echo back the raw string.
        return "postgresql://[REDACTED]"

    port = f":{parsed.port}" if parsed.port else ""
    path = parsed.path or ""
    # Drop userinfo, query and fragment entirely.
    netloc = f"{host}{port}"
    return urlunparse(parsed._replace(
        netloc=netloc, query="", params="", fragment="", path=path,
    ))


class Settings(BaseSettings):
    app_env: str = "development"
    app_base_url: str = "http://127.0.0.1:8000"
    database_path: str = "var/personal-edition.db"
    db_backend: str = "sqlite"
    # Use PE_DATABASE_URL env alias to avoid colliding with the ambient
    # DATABASE_URL that many parent environments (including this repo's
    # other apps) export.  The Personal Edition must never implicitly
    # pick up another app's PostgreSQL URL.
    database_url: str = Field(
        default="",
        validation_alias=AliasChoices("PE_DATABASE_URL"),
    )
    ai_provider: str = "mock"
    ai_model: str = "mock-personal-edition-v1"
    ai_base_url: str = ""
    ai_api_key: str = ""
    ai_timeout_seconds: int = Field(default=120, gt=0)
    ai_cost_class: str = "free"
    ai_response_format_mode: str = "json_schema"
    prompt_version: str = "personal-edition-v1"
    secret_key: str = "dev-secret-key-change-in-production"
    admin_secret: str = "dev-admin-secret-change-in-production"
    session_max_age_seconds: int = Field(default=3600 * 8, gt=0)
    cookie_secure: bool = False
    cookie_samesite: str = "lax"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @model_validator(mode="after")
    def _validate_production_secrets(self):
        if self.app_env == "production":
            if self.secret_key in _DEFAULT_SECRETS or len(self.secret_key) < 32:
                raise ValueError(
                    "SECRET_KEY must be set to a strong, unique value "
                    "in production (APP_ENV=production)"
                )
            if self.admin_secret in _DEFAULT_SECRETS or len(self.admin_secret) < 16:
                raise ValueError(
                    "ADMIN_SECRET must be set to a strong, unique value "
                    "in production (APP_ENV=production)"
                )
            if not self.cookie_secure:
                raise ValueError(
                    "COOKIE_SECURE must be true in production "
                    "(APP_ENV=production)"
                )
        return self

    @model_validator(mode="after")
    def _validate_db_backend(self):
        if self.db_backend not in _VALID_DB_BACKENDS:
            raise ValueError(
                f"DB_BACKEND must be one of {sorted(_VALID_DB_BACKENDS)}, "
                f"got '{self.db_backend}'"
            )

        if self.db_backend == "postgresql":
            if not self.database_url:
                raise ValueError(
                    "DATABASE_URL is required when DB_BACKEND=postgresql"
                )
            if not _POSTGRES_URL_RE.match(self.database_url):
                raise ValueError(
                    "DATABASE_URL must be a valid PostgreSQL connection URL "
                    "when DB_BACKEND=postgresql"
                )
        else:
            # sqlite backend — production must not silently fall back to SQLite
            # when a PostgreSQL URL was provided, and production must not use
            # the default SQLite path without an explicit override.
            if self.database_url:
                raise ValueError(
                    "DATABASE_URL must not be set when DB_BACKEND=sqlite"
                )
            if self.app_env == "production":
                if self.database_path == "var/personal-edition.db":
                    raise ValueError(
                        "DATABASE_PATH must be explicitly set in production "
                        "(APP_ENV=production, DB_BACKEND=sqlite)"
                    )
        return self

    @model_validator(mode="after")
    def _validate_provider_config(self):
        if self.ai_provider not in _VALID_PROVIDERS:
            raise ValueError(
                f"AI_PROVIDER must be one of {sorted(_VALID_PROVIDERS)}, "
                f"got '{self.ai_provider}'"
            )
        if self.ai_cost_class not in _VALID_COST_CLASSES:
            raise ValueError(
                f"AI_COST_CLASS must be one of {sorted(_VALID_COST_CLASSES)}, "
                f"got '{self.ai_cost_class}'"
            )
        if self.ai_response_format_mode not in _VALID_RESPONSE_FORMAT_MODES:
            raise ValueError(
                f"AI_RESPONSE_FORMAT_MODE must be one of "
                f"{sorted(_VALID_RESPONSE_FORMAT_MODES)}, "
                f"got '{self.ai_response_format_mode}'"
            )
        if self.ai_provider == "external":
            if not self.ai_base_url:
                raise ValueError(
                    "AI_BASE_URL is required when AI_PROVIDER=external"
                )
            if not self.ai_api_key:
                raise ValueError(
                    "AI_API_KEY is required when AI_PROVIDER=external"
                )
            if not self.ai_model or self.ai_model == "mock-personal-edition-v1":
                raise ValueError(
                    "AI_MODEL must be set to a non-default value when "
                    "AI_PROVIDER=external"
                )
            if self.app_env == "production" and not self.ai_base_url.startswith("https://"):
                raise ValueError(
                    "AI_BASE_URL must use HTTPS in production"
                )
        return self

    def __repr__(self) -> str:
        """Redact sensitive fields in repr to prevent credential leakage."""
        base = super().__repr__()
        if self.database_url:
            safe = redact_database_url(self.database_url)
            # Replace the raw URL with the redacted version in the repr.
            base = base.replace(self.database_url, safe)
        return base


settings = Settings()
