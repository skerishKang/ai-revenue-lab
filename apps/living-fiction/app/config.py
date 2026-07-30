"""Living Fiction configuration.

Environment-backed settings via pydantic-settings. No hardcoded secrets.
The MockProvider is the default and only provider in Phase 1.

Phase 2 adds web session and credential HMAC keys. All secrets are
injected via environment variables — no fallback defaults are provided
for security-sensitive fields.
"""

from urllib.parse import urlparse

from pydantic_settings import BaseSettings

_PLACEHOLDER_SECRETS = {
    "changeme",
    "change-me",
    "change_me",
    "secret",
    "password",
    "example",
    "placeholder",
}


def _structurally_weak(value: str) -> bool:
    """Minimal structural-weakness check for a production secret.

    This is deliberately NOT an entropy measurement — it makes no claim about
    the randomness of a value. It only rejects secrets that are obviously
    unfit for production:

    * empty or whitespace-dominated strings;
    * a single repeated character (``"aaaa..."``);
    * a short repeating pattern (``"ababab..."``, ``"abcabcabc..."``);
    * a value built around a known placeholder, including prefix/suffix and
      repetition variants (``"changeme"``, ``"my-changeme-1"``,
      ``"passwordpassword..."``).

    A value that passes here is merely "not obviously weak"; it is still the
    operator's responsibility to use a genuinely random secret.
    """
    stripped = value.strip()
    if not stripped:
        return True
    # Whitespace-dominated: more than half the characters are whitespace.
    if len(stripped) * 2 < len(value):
        return True
    # Single repeated character.
    if len(set(stripped)) == 1:
        return True
    # Short repeating pattern: the whole value is a short unit repeated 3+ times.
    for period in range(2, 9):
        if len(stripped) % period == 0 and len(stripped) >= period * 3:
            unit = stripped[:period]
            if unit * (len(stripped) // period) == stripped:
                return True
    # Known placeholder, or a prefix/suffix/repeat variant of one.
    lowered = stripped.lower()
    for placeholder in _PLACEHOLDER_SECRETS:
        if placeholder in lowered:
            return True
    return False


def canonicalize_origin(origin: str) -> str | None:
    """Normalize an origin to canonical ``scheme://host[:port]`` form.

    Returns ``None`` for anything that is not a well-formed absolute
    ``http://``/``https://`` origin so callers reject it with a generic 403
    rather than crashing. This deliberately absorbs the ``ValueError`` that
    :mod:`urllib.parse` raises for malformed or out-of-range ports
    (``https://example.com:notaport``, ``https://example.com:99999``) and for
    malformed IPv6 literals (``https://[invalid``).

    The canonical form lowercases the scheme and host, drops default ports
    (80 for http, 443 for https), and carries no trailing slash. IPv6 hosts are
    re-bracketed so the result stays a valid URL host (``http://[::1]:8000``).
    Canonicalization makes allowlist matching robust to superficial differences
    such as ``HTTPS://Example.com/`` vs ``https://example.com`` or
    ``https://example.com:443`` vs ``https://example.com``.
    """
    try:
        parsed = urlparse(origin.strip())
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    try:
        host = parsed.hostname
    except ValueError:
        return None
    if not host:
        return None
    if parsed.path not in ("", "/"):
        return None
    if parsed.query or parsed.fragment:
        return None
    if parsed.username or parsed.password:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    scheme = parsed.scheme.lower()
    # ``hostname`` is already lowercased; re-bracket IPv6 literals so the
    # canonical origin remains a valid URL host.
    host = f"[{host}]" if ":" in host else host
    default_port = 443 if scheme == "https" else 80
    if port is not None and port != default_port:
        return f"{scheme}://{host}:{port}"
    return f"{scheme}://{host}"


class Settings(BaseSettings):
    env: str = "development"
    app_name: str = "living-fiction"

    # Database backend selection. The backend is chosen EXPLICITLY; it is never
    # inferred from the shape of a URL. ``sqlite`` is the local default;
    # ``postgres`` is the only backend allowed in production.
    database_backend: str = "sqlite"
    database_path: str = "var/living-fiction.db"
    # Runtime pooled PostgreSQL URL (postgres backend only). Treated as a
    # secret: never logged or included in error messages.
    database_url: str = ""
    # Owner/migration-role direct PostgreSQL URL used only by the migration
    # command. Treated as a secret: never logged or included in error messages.
    migration_database_url: str = ""
    # Small bounded pool; sized so an idle deployment can scale to zero.
    database_pool_max_size: int = 5

    ai_provider: str = "mock"
    ai_model: str = "mock-living-fiction-v1"
    ai_api_key: str = ""
    ai_base_url: str = ""
    prompt_version: str = "living-fiction-v1"
    max_retries: int = 2

    def validate_ai_provider(self) -> None:
        provider = (self.ai_provider or "").strip().lower()
        if provider == "mock":
            return
        if provider not in ("opencode_go", "openai_compat"):
            raise ValueError(
                f"LF_AI_PROVIDER must be 'mock', 'opencode_go', "
                f"or 'openai_compat'; got '{provider}'"
            )
        if not self.ai_api_key:
            raise ValueError(
                "LF_AI_API_KEY is required when LF_AI_PROVIDER "
                "is not 'mock'"
            )
        if not self.ai_model:
            raise ValueError(
                "LF_AI_MODEL is required when LF_AI_PROVIDER "
                "is not 'mock'"
            )
        if provider == "openai_compat":
            if not self.ai_base_url or not self.ai_base_url.strip():
                raise ValueError(
                    "LF_AI_BASE_URL is required when LF_AI_PROVIDER "
                    "is 'openai_compat'"
                )

    # Phase 2 web security settings — no fallback defaults.
    admin_secret: str = ""
    credential_hmac_key: str = ""
    session_hmac_key: str = ""

    # Comma-separated list of allowed request origins (scheme://host[:port])
    # for state-changing requests. Used for Origin/Host verification in
    # production; empty means "derive from the request Host" (lenient only
    # outside production).
    allowed_origins: str = ""

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "env_prefix": "LF_",
    }

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    def validate_web_secrets(self) -> None:
        """Fail closed when web secrets are missing or (in production) weak.

        Every environment requires all three secrets to be non-empty. In
        production they must additionally be at least 32 characters, mutually
        distinct, and not obvious placeholders — there is no source-code
        fallback for any secret.
        """
        secrets = {
            "LF_ADMIN_SECRET": self.admin_secret,
            "LF_CREDENTIAL_HMAC_KEY": self.credential_hmac_key,
            "LF_SESSION_HMAC_KEY": self.session_hmac_key,
        }
        missing = [name for name, value in secrets.items() if not value]
        if missing:
            raise ValueError(
                "Missing required web secret(s): " + ", ".join(missing)
            )
        if not self.is_production:
            return
        for name, value in secrets.items():
            if len(value) < 32:
                raise ValueError(
                    f"{name} must be at least 32 characters in production"
                )
            if _structurally_weak(value):
                raise ValueError(
                    f"{name} is structurally weak (repeated, patterned, or "
                    "placeholder-like); set a genuinely random secret"
                )
        values = list(secrets.values())
        if len(set(values)) != len(values):
            raise ValueError("Web secrets must be distinct from one another")

    def validate_allowed_origins(self) -> None:
        """Validate ``LF_ALLOWED_ORIGINS`` for production.

        In production the allowlist must be non-empty and every entry must be a
        well-formed ``http://`` or ``https://`` origin with no path, query,
        fragment, or embedded credentials. Validation fails closed: if any entry
        is invalid — including malformed or out-of-range ports and malformed
        IPv6 literals that only the canonicalizer detects — startup is rejected
        rather than silently dropping the entry and weakening the allowlist.
        Valid duplicate entries are normalized away (deduplicated). The actual
        configured values are never included in error messages so a
        misconfigured secret is not leaked into logs.

        Outside production the check is skipped so localhost / TestClient
        workflows work without configuration.
        """
        if not self.is_production:
            return
        raw = [o.strip() for o in self.allowed_origins.split(",") if o.strip()]
        if not raw:
            raise ValueError(
                "LF_ALLOWED_ORIGINS must not be empty in production"
            )
        seen: set[str] = set()
        for origin in raw:
            try:
                parsed = urlparse(origin)
            except ValueError:
                # urlparse cannot parse this input at all (e.g. an invalid IPv6
                # literal). Fail closed rather than silently dropping the entry.
                raise ValueError(
                    "LF_ALLOWED_ORIGINS contains an invalid origin"
                ) from None
            if parsed.scheme not in ("http", "https"):
                raise ValueError(
                    "LF_ALLOWED_ORIGINS entries must use http:// or https://"
                )
            if not parsed.netloc:
                raise ValueError(
                    "LF_ALLOWED_ORIGINS entries must include a host"
                )
            if parsed.path not in ("", "/"):
                raise ValueError(
                    "LF_ALLOWED_ORIGINS entries must not include a path"
                )
            if parsed.query or parsed.fragment:
                raise ValueError(
                    "LF_ALLOWED_ORIGINS entries must not include query or fragment"
                )
            if parsed.username or parsed.password:
                raise ValueError(
                    "LF_ALLOWED_ORIGINS entries must not include credentials"
                )
            # Fail closed on anything the canonicalizer rejects — malformed or
            # out-of-range ports and malformed IPv6 literals that the urlparse
            # checks above do not catch. Silently dropping such an entry would
            # weaken the allowlist, so reject the whole configuration. Valid
            # origins collapse to one canonical form (case / trailing slash /
            # explicit default port) so equivalents deduplicate.
            canonical = canonicalize_origin(origin)
            if canonical is None:
                raise ValueError(
                    "LF_ALLOWED_ORIGINS contains an invalid origin"
                )
            seen.add(canonical)
        if not seen:
            raise ValueError(
                "LF_ALLOWED_ORIGINS must contain at least one valid origin"
            )
        # Normalize duplicates silently (no error, just dedup).
        self.allowed_origins = ",".join(sorted(seen))

    def validate_database(self) -> None:
        """Validate the database backend selection, failing closed.

        Rules:
          * ``LF_DATABASE_BACKEND`` must be exactly ``sqlite`` or ``postgres``
            (case-insensitive). The backend is never inferred from a URL.
          * Production allows only ``postgres``; ``production`` + ``sqlite``
            fails closed so a file-backed DB can never serve production traffic.
          * ``postgres`` requires a runtime ``LF_DATABASE_URL``; its absence
            fails closed.

        Error messages are generic and never include the configured URL or any
        credential, so a misconfigured secret cannot leak into logs or startup
        output.
        """
        from app.database.url import is_postgres_url  # noqa: PLC0415

        backend = (self.database_backend or "").strip().lower()
        if backend not in ("sqlite", "postgres"):
            raise ValueError(
                "LF_DATABASE_BACKEND must be 'sqlite' or 'postgres'"
            )
        self.database_backend = backend
        if backend == "sqlite" and self.is_production:
            raise ValueError(
                "production requires the postgres database backend "
                "(LF_DATABASE_BACKEND=postgres)"
            )
        if backend == "postgres":
            if not self.database_url.strip():
                raise ValueError(
                    "postgres backend requires LF_DATABASE_URL to be set"
                )
            if not is_postgres_url(self.database_url):
                raise ValueError(
                    "LF_DATABASE_URL is not a valid PostgreSQL connection URL"
                )


settings = Settings()
