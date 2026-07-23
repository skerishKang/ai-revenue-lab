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

    Returns ``None`` when *origin* is not a well-formed ``http://``/``https://``
    origin (missing host, or carrying a path/query/fragment/embedded
    credentials). Otherwise returns the canonical form: lowercased scheme and
    host, default ports dropped (80 for http, 443 for https), and no trailing
    slash. Canonicalization makes allowlist matching robust to superficial
    differences such as ``HTTPS://Example.com/`` vs ``https://example.com`` or
    ``https://example.com:443`` vs ``https://example.com``.
    """
    parsed = urlparse(origin.strip())
    if parsed.scheme not in ("http", "https"):
        return None
    host = parsed.hostname
    if not host:
        return None
    if parsed.path not in ("", "/"):
        return None
    if parsed.query or parsed.fragment:
        return None
    if parsed.username or parsed.password:
        return None
    scheme = parsed.scheme.lower()
    host = host.lower()
    port = parsed.port
    default_port = 443 if scheme == "https" else 80
    if port is not None and port != default_port:
        return f"{scheme}://{host}:{port}"
    return f"{scheme}://{host}"


class Settings(BaseSettings):
    env: str = "development"
    app_name: str = "living-fiction"
    database_path: str = "var/living-fiction.db"
    ai_provider: str = "mock"
    ai_model: str = "mock-living-fiction-v1"
    prompt_version: str = "living-fiction-v1"
    max_retries: int = 2

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
        fragment, or embedded credentials. Duplicate entries are silently
        normalized away. The actual configured values are never included in
        error messages so a misconfigured secret is not leaked into logs.

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
            parsed = urlparse(origin)
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
            # Store the canonical form so equivalent origins (differing only by
            # case, trailing slash, or explicit default port) collapse to one.
            canonical = canonicalize_origin(origin)
            if canonical is not None:
                seen.add(canonical)
        # Normalize duplicates silently (no error, just dedup).
        self.allowed_origins = ",".join(sorted(seen))


settings = Settings()
