"""OpenRouter adapter configuration for Business 14 Alpha.

Reads B14_-prefixed and OPENROUTER_API_KEY environment variables.
The API key is never exposed to the browser, never logged, and only
read from server-side environment variables.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

from app.pilot.redaction import redact_sensitive

ALLOWED_OPENROUTER_HOSTS = frozenset({
    "openrouter.ai",
    "openrouter.ai.",
})

DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_SITE_NAME = "Business 14 Korean AI Gateway"

_PROVIDER_MODES = frozenset({"mock", "live"})


class OpenRouterConfig:
    """Configuration for the OpenRouter provider adapter."""

    def __init__(self) -> None:
        import os

        self.api_key: str = os.environ.get("OPENROUTER_API_KEY", "")
        raw_mode = os.environ.get("B14_PROVIDER_MODE", "mock").strip().lower()
        self.provider_mode: str = raw_mode if raw_mode in _PROVIDER_MODES else "mock"

        raw_url = os.environ.get("B14_OPENROUTER_BASE_URL", DEFAULT_OPENROUTER_BASE_URL).strip()
        self.base_url: str = raw_url or DEFAULT_OPENROUTER_BASE_URL

        self.site_url: str = os.environ.get("B14_SITE_URL", "").strip()
        self.site_name: str = (
            os.environ.get("B14_SITE_NAME", DEFAULT_SITE_NAME).strip()
            or DEFAULT_SITE_NAME
        )

        self.connect_timeout_seconds: float = 10.0
        self.read_timeout_seconds: float = 30.0
        self.write_timeout_seconds: float = 10.0
        self.pool_timeout_seconds: float = 10.0
        self.max_response_bytes: int = 1024 * 1024
        self.max_error_body_chars: int = 500

    def build_http_timeout(self):
        """Build the httpx.Timeout with every component set explicitly.

        No implicit default: connect/read/write/pool are each bounded and
        match the documented values. There is no separate "total" deadline —
        the per-phase bounds are the contract.
        """
        import httpx

        return httpx.Timeout(
            None,
            connect=self.connect_timeout_seconds,
            read=self.read_timeout_seconds,
            write=self.write_timeout_seconds,
            pool=self.pool_timeout_seconds,
        )

    @property
    def is_live(self) -> bool:
        return self.provider_mode == "live"

    @property
    def is_mock(self) -> bool:
        return self.provider_mode == "mock"

    @property
    def has_key(self) -> bool:
        return bool(self.api_key) and not _looks_like_placeholder(self.api_key)

    def validate_base_url(self, url: str | None = None) -> None:
        """Validate that a URL targets an allowed OpenRouter host (no SSRF)."""
        target = url or self.base_url
        parsed = urlparse(target)
        if parsed.scheme != "https":
            raise ValueError("OpenRouter base URL must use https://")
        if parsed.username or parsed.password:
            raise ValueError("OpenRouter base URL must not contain credentials")
        if parsed.fragment:
            raise ValueError("OpenRouter base URL must not contain a fragment")
        if parsed.query:
            raise ValueError("OpenRouter base URL must not contain a query string")
        host = parsed.hostname
        if not host:
            raise ValueError("OpenRouter base URL must have a hostname")
        host_lower = host.lower()
        if host_lower not in ALLOWED_OPENROUTER_HOSTS:
            raise ValueError(f"OpenRouter base URL host not in allow-list: {host}")
        try:
            addr = ipaddress.ip_address(host_lower)
        except ValueError:
            return
        if (
            addr.is_loopback
            or addr.is_private
            or addr.is_link_local
            or addr.is_unspecified
            or addr.is_multicast
            or addr.is_reserved
        ):
            raise ValueError("OpenRouter base URL must not point to a non-routable address")

    def safe_headers(self) -> dict[str, str]:
        """Build HTTP headers for OpenRouter requests (key NOT in header dict key name)."""
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "HTTP-Referer": self.site_url if self.site_url else "https://business14.example",
            "X-OpenRouter-Title": self.site_name,
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def redacted_summary(self) -> str:
        """Return a redacted summary string for logging."""
        return (
            f"mode={self.provider_mode} "
            f"has_key={'yes' if self.has_key else 'no'} "
            f"base_url={redact_sensitive(self.base_url)}"
        )


def _looks_like_placeholder(key: str) -> str | None:
    """Return True-ish if the key looks like a placeholder."""
    if not key:
        return ""
    lower = key.lower().strip()
    placeholders = (
        "sk-your",
        "your-api-key",
        "test-key",
        "demo-key",
        "placeholder",
        "$openrouter_api_key",
        "your-openrouter",
    )
    for p in placeholders:
        if p in lower:
            return p
    if len(key) < 8:
        return "too_short"
    return ""


openrouter_config = OpenRouterConfig()
