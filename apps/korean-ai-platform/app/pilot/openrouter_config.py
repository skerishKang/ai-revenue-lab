"""OpenRouter adapter configuration for Business 14 Alpha (pruned).

Only the provider_mode, is_live, is_mock, build_http_timeout, max_response_bytes
fields and redacted_summary() are retained. All secret-backed and URL-backed
fields have been retired per decision #1933 §3 disposal table.
"""

from __future__ import annotations

from app.pilot.redaction import redact_sensitive

_PROVIDER_MODES = frozenset({"mock", "live"})


class OpenRouterConfig:
    """Configuration for the OpenRouter provider adapter (pruned)."""

    def __init__(self) -> None:
        import os

        raw_mode = os.environ.get("B14_PROVIDER_MODE", "mock").strip().lower()
        self.provider_mode: str = raw_mode if raw_mode in _PROVIDER_MODES else "mock"
        self.max_response_bytes: int = 1024 * 1024

    def build_http_timeout(self):
        """Build httpx.Timeout with inlined per-phase bounds."""
        import httpx

        return httpx.Timeout(
            None,
            connect=10.0,
            read=30.0,
            write=10.0,
            pool=10.0,
        )

    @property
    def is_live(self) -> bool:
        return self.provider_mode == "live"

    @property
    def is_mock(self) -> bool:
        return self.provider_mode == "mock"

    def redacted_summary(self) -> str:
        """Return a redacted summary string for logging."""
        return f"mode={self.provider_mode} max_response_bytes={self.max_response_bytes}"


openrouter_config = OpenRouterConfig()
