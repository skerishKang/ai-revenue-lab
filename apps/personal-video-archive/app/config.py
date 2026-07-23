"""Configuration for Personal Video Archive."""

from __future__ import annotations

from urllib.parse import urlparse

from pydantic import Field
from pydantic_settings import BaseSettings

_VALID_DISCOVERY_PROVIDERS = frozenset({"fake"})
_VALID_LLM_PROVIDERS = frozenset({"fake"})

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "[::1]"})


def safe_portal_base(raw: str) -> str:
    """Return a validated portal base URL, or "" when absent or unsafe.

    Policy: HTTPS bases with a host are accepted; plain-HTTP bases are
    accepted only for loopback hosts during local development. Anything
    else (insecure remote HTTP, relative paths, credentials, garbage)
    fails closed to "" so templates render safe non-navigating controls.
    """
    candidate = (raw or "").strip()
    if not candidate:
        return ""
    parsed = urlparse(candidate)
    if parsed.username or parsed.password:
        return ""
    host = (parsed.hostname or "").lower()
    if not host:
        return ""
    if parsed.scheme == "https":
        pass
    elif parsed.scheme == "http" and host in _LOOPBACK_HOSTS:
        pass
    else:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")


class Settings(BaseSettings):
    app_env: str = "development"
    app_base_url: str = "http://127.0.0.1:8000"
    database_path: str = "var/personal-video-archive.db"

    discovery_provider: str = "fake"
    llm_provider: str = "fake"
    llm_model: str = "fake-pva-v1"

    # No real API key is accepted in Phase 1.
    youtube_api_key: str = ""

    # Optional AI Revenue Lab portal base (see ADR-0003 / Issue #83).
    # Validated lazily through ``portal_base``; unsafe values fail closed.
    portal_base_url: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def portal_base(self) -> str:
        return safe_portal_base(self.portal_base_url)

    @property
    def portal_home_href(self) -> str:
        base = self.portal_base
        return f"{base}/" if base else ""

    @property
    def portal_account_href(self) -> str:
        base = self.portal_base
        return f"{base}/account" if base else ""


settings = Settings()
