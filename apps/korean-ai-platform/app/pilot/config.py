"""BYOK Gateway Pilot configuration.

Provides raw env-var accessors only. Configuration state resolution
(delegating to routing.PilotConfigurationState) happens in routing.py.

Raw accessors provided:
- has_registry: provider_registry_json is non-empty
- has_legacy: both pilot_base_url and pilot_model_id are set
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
    def has_registry(self) -> bool:
        return bool(self.provider_registry_json)

    @property
    def has_legacy(self) -> bool:
        return bool(self.pilot_base_url and self.pilot_model_id)

    @property
    def configured(self) -> bool:
        """Quick check: any configuration source has data (may be invalid).
        Full validation is done by routing.resolve_configuration()."""
        return self.has_registry or self.has_legacy

    @property
    def mode_name(self) -> str:
        """Quick mode label (not validated)."""
        if self.provider_registry_json:
            return "byok-multi-provider-pilot"
        if self.pilot_base_url and self.pilot_model_id:
            return "byok-pilot"
        return "not_configured"


pilot_settings = PilotSettings()
