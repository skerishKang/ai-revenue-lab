"""B14 runtime mode/timeout configuration.

Only the provider_mode, is_live, is_mock, build_http_timeout, max_response_bytes
fields and redacted_summary() are retained. All secret-backed and URL-backed
fields have been retired per decision #1933 §3 disposal table.

``max_response_bytes`` is declared-only metadata: no response-collection path
reads it. The effective completed and streamed byte guard is
``app.pilot.platform.MAX_RESPONSE_BYTES`` (census and the staged knob proposal:
docs/operations/B14_RESPONSE_BYTE_CAP_CONTRACT_2026-10-13.md). Editing this
field cannot raise or lower a live limit, so it must not be presented to an
operator as a model output setting.
"""

from __future__ import annotations

from app.pilot.redaction import redact_sensitive

_PROVIDER_MODES = frozenset({"mock", "live"})


class B14RuntimeConfig:
    """B14 runtime mode/timeout config."""

    def __init__(self) -> None:
        import os

        raw_mode = os.environ.get("B14_PROVIDER_MODE", "mock").strip().lower()
        self.provider_mode: str = raw_mode if raw_mode in _PROVIDER_MODES else "mock"
        # Declared-only: no env, secret or admin input reaches this field.
        self.max_response_bytes: int = 1024 * 1024

    def build_http_timeout(self):
        """Build httpx.Timeout with inlined per-phase bounds."""
        from app.pilot.b14_timeout_policy import build_provider_http_timeout

        return build_provider_http_timeout()

    @property
    def is_live(self) -> bool:
        return self.provider_mode == "live"

    @property
    def is_mock(self) -> bool:
        return self.provider_mode == "mock"

    def redacted_summary(self) -> str:
        """Return a redacted summary string for logging.

        ``max_response_bytes_effect=no`` is part of the contract: reading this
        line must not suggest the model response size is adjustable here.
        """
        return (
            f"mode={self.provider_mode} "
            f"max_response_bytes={self.max_response_bytes} "
            "max_response_bytes_effect=no"
        )


runtime_config = B14RuntimeConfig()
