"""Pilot model listing for UI display.

Returns the configured pilot model(s). Empty when not configured.
"""

from __future__ import annotations

from app.pilot.config import pilot_settings


def get_pilot_models() -> list[dict]:
    """Return a list of pilot-available models for UI display."""
    if not pilot_settings.configured:
        return []
    display_name = pilot_settings.pilot_model_id.replace("-", " ").title()
    return [
        {
            "id": pilot_settings.pilot_model_id,
            "name": f"{display_name} (Pilot)",
            "provider_id": pilot_settings.pilot_provider_id,
            "provider_name": pilot_settings.pilot_provider_id.replace("-", " ").title(),
            "pilot_available": True,
        }
    ]
