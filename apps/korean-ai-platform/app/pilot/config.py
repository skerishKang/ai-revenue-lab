"""BYOK Gateway Pilot configuration.

Reads BUSINESS14_-prefixed environment variables via os.environ.
Replaces pydantic-settings BaseSettings to avoid bundling
pydantic-core (4 MiB WASM binary) in Cloudflare Workers.
"""

from __future__ import annotations

import os


class PilotSettings:
    """BYOK Gateway Pilot configuration."""

    pilot_provider_id: str = "pilot-openai-compat"
    pilot_base_url: str = ""
    pilot_model_id: str = ""
    pilot_upstream_model: str = ""
    pilot_timeout_seconds: int = 30
    provider_registry_json: str = ""

    def __init__(self) -> None:
        self.pilot_provider_id = os.environ.get(
            "BUSINESS14_PILOT_PROVIDER_ID", "pilot-openai-compat"
        )
        self.pilot_base_url = os.environ.get("BUSINESS14_PILOT_BASE_URL", "")
        self.pilot_model_id = os.environ.get("BUSINESS14_PILOT_MODEL_ID", "")
        self.pilot_upstream_model = os.environ.get(
            "BUSINESS14_PILOT_UPSTREAM_MODEL", ""
        )
        try:
            self.pilot_timeout_seconds = int(
                os.environ.get("BUSINESS14_PILOT_TIMEOUT_SECONDS", "30")
            )
        except (ValueError, TypeError):
            self.pilot_timeout_seconds = 30
        self.provider_registry_json = os.environ.get(
            "BUSINESS14_PROVIDER_REGISTRY_JSON", ""
        )

    @property
    def has_registry(self) -> bool:
        return bool(self.provider_registry_json)

    @property
    def has_legacy(self) -> bool:
        return bool(self.pilot_base_url and self.pilot_model_id)

    @property
    def configured(self) -> bool:
        return self.has_registry or self.has_legacy

    @property
    def mode_name(self) -> str:
        if self.provider_registry_json:
            return "byok-multi-provider-pilot"
        if self.pilot_base_url and self.pilot_model_id:
            return "byok-pilot"
        return "not_configured"


pilot_settings = PilotSettings()
