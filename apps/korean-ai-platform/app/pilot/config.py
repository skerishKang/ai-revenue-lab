"""BYOK Gateway Pilot configuration.

All pilot settings are loaded from environment variables at startup.
No provider credentials or endpoint URLs are hardcoded.
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

    model_config = {"env_prefix": "BUSINESS14_"}

    @property
    def configured(self) -> bool:
        return bool(self.pilot_base_url and self.pilot_model_id)


pilot_settings = PilotSettings()
