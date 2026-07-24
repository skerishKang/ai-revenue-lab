"""BYOK Gateway Pilot configuration.

Supports multi-provider registry via BUSINESS14_PROVIDER_REGISTRY_JSON
with legacy single-provider fallback via BUSINESS14_PILOT_* variables.

Config states (checked at runtime via registry):
- valid_registry: registry JSON valid
- invalid_registry: registry JSON present but invalid → fail-closed
- legacy: single-provider env vars configured
- not_configured: nothing configured
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
        """True if configuration is usable.

        - registry JSON present and parseable → True (full validation at registry init)
        - registry JSON present but unparseable → False (fail-closed; UI shows invalid_registry)
        - legacy single-provider → True
        - nothing → False
        """
        if self.provider_registry_json:
            try:
                import json
                json.loads(self.provider_registry_json)
                return True
            except (json.JSONDecodeError, ValueError):
                return False
        return bool(self.pilot_base_url and self.pilot_model_id)

    @property
    def has_registry(self) -> bool:
        return bool(self.provider_registry_json)

    @property
    def has_legacy(self) -> bool:
        return bool(self.pilot_base_url and self.pilot_model_id)

    @property
    def mode_name(self) -> str:
        if self.provider_registry_json:
            return "byok-multi-provider-pilot"
        if self.pilot_base_url and self.pilot_model_id:
            return "byok-pilot"
        return "not_configured"


pilot_settings = PilotSettings()
