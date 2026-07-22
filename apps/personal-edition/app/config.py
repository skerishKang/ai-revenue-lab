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

    This function **never raises** — it is called outside the CLI's main
    ``try`` block (before connection) so any exception would surface as an
    uncaught traceback.  Malformed postgres URLs (bad port, bad IPv6,
    percent-encoding errors, missing host, etc.) are all reduced to a fixed
    placeholder so that no partial userinfo can leak.

    For non-postgres URLs (e.g. SQLite paths) the query string is stripped as
    a best-effort and the rest is returned unchanged.
    """
    if not isinstance(url, str) or not url:
        return url

    try:
        parsed = urlparse(url)
        scheme = (parsed.scheme or "").lower()
    except Exception:
        # Even urlparse itself can raise on some malformed inputs.
        return _PG_REDACTED_PLACEHOLDER if _looks_like_postgres(url) else url.split("?", 1)[0]

    if scheme not in ("postgresql", "postgres"):
        # Not a postgres URL (e.g. SQLite path) — no userinfo to redact.
        return url.split("?", 1)[0]

    # All extraction must be exception-safe: parsed.port raises ValueError on
    # non-numeric ports, and percent-decoding/IPv6 edge cases can also raise.
    try:
        host = parsed.hostname
        port = parsed.port  # may raise ValueError -> caught below
        path = parsed.path or ""
    except Exception:
        return _PG_REDACTED_PLACEHOLDER

    if not host:
        # Malformed postgres URL — never echo back the raw string.
        return _PG_REDACTED_PLACEHOLDER

    port_part = f":{port}" if port else ""
    netloc = f"{host}{port_part}"
    try:
        return urlunparse(parsed._replace(
            netloc=netloc, query="", params="", fragment="", path=path,
        ))
    except Exception:
        return _PG_REDACTED_PLACEHOLDER


_PG_REDACTED_PLACEHOLDER = "postgresql://[REDACTED]"


def _looks_like_postgres(url: str) -> bool:
    """Best-effort check whether a string is a postgres-family URL."""
    low = url.lower()
    return low.startswith("postgresql://") or low.startswith("postgres://")


def normalize_pg_url_identity(url: str) -> tuple[str, str, str] | None:
    """Return a normalized ``(host, port, database)`` identity for a PG URL.

    This performs NO network connection — it only parses the URL.  The
    identity is used to detect when two different URL strings point at the
    same database (e.g. differing only by userinfo, query parameters, or a
    default-port omission).  Returns ``None`` if the URL cannot be parsed
    as a postgres URL (in which case the caller should treat it as
    non-matching rather than equivalent).

    The default PostgreSQL port (5432) is normalized so that
    ``host:5432/db`` and ``host/db`` compare equal.  Hostnames are
    lower-cased for case-insensitive comparison.
    """
    if not isinstance(url, str) or not url:
        return None
    try:
        parsed = urlparse(url)
    except Exception:
        return None
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("postgresql", "postgres"):
        return None
    try:
        host = (parsed.hostname or "").lower()
        port = parsed.port  # may raise ValueError
    except Exception:
        return None
    if not host:
        return None
    if port is None:
        port = 5432
    path = parsed.path or ""
    # Strip leading slash so "/db" and "db" compare equal.
    db = path.lstrip("/")
    return (host, str(port), db)


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
