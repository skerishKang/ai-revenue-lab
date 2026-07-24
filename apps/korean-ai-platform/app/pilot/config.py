"""BYOK Gateway Pilot configuration.

Supports multi-provider registry via BUSINESS14_PROVIDER_REGISTRY_JSON
with legacy single-provider fallback via BUSINESS14_PILOT_* variables.

Priority:
1. Valid multi-provider registry → use registry
2. Single-provider variables → use legacy mode
3. Neither → not configured
"""

from __future__ import annotations

from pydantic_settings import BaseSettings


class PilotSettings(BaseSettings):
    """BYOK Gateway Pilot configuration."""

    pilot_provider_id: str = "pilot-openai-compat"
    pilot_base_url: str = ""
    pilot_model_id: str = ""
    pilot_upstream_model: str = ""
    pilot_timeout_seconds: int = 30
    provider_registry_json: str = ""

    model_config = {"env_prefix": "BUSINESS14_"}

    @property
    def configured(self) -> bool:
        if self.provider_registry_json:
            return True
        return bool(self.pilot_base_url and self.pilot_model_id)

    @property
    def has_registry(self) -> bool:
        return bool(self.provider_registry_json)

    @property
    def mode_name(self) -> str:
        if self.provider_registry_json:
            return "byok-multi-provider-pilot"
        if self.pilot_base_url and self.pilot_model_id:
            return "byok-pilot"
        return "not_configured"


pilot_settings = PilotSettings()
