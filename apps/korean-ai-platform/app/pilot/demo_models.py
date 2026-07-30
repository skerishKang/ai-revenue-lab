"""Pilot model listing for UI display.

Phase 2: supports multi-provider registry and legacy single-provider fallback.
Empty when not configured.
"""

from __future__ import annotations

from app.pilot.config import pilot_settings
from app.pilot.registry import get_registry


def get_pilot_models() -> list[dict]:
    """Return a list of pilot-available models for UI display.

    Priority:
    1. Multi-provider registry models
    2. Legacy single-provider model
    3. Empty list (not configured)
    """
    registry = get_registry()
    if registry.configured:
        return registry.list_models()

    if not pilot_settings.configured:
        return []

    display_name = pilot_settings.pilot_model_id.replace("-", " ").title()
    provider_name = pilot_settings.pilot_provider_id.replace("-", " ").title()
    return [
        {
            "id": pilot_settings.pilot_model_id,
            "name": f"{display_name} (Pilot)",
            "provider_id": pilot_settings.pilot_provider_id,
            "provider_name": provider_name,
            "pilot_available": True,
        }
    ]


def get_pilot_provider_summary() -> list[dict]:
    """Return provider count summary for UI."""
    registry = get_registry()
    if registry.configured:
        return registry.provider_summary()
    if pilot_settings.configured:
        return [{"provider_id": pilot_settings.pilot_provider_id, "model_count": 1}]
    return []


def get_pilot_model_count() -> int:
    """Return total enabled model count."""
    registry = get_registry()
    if registry.configured:
        return registry.model_count
    if pilot_settings.configured:
        return 1
    return 0


def get_pilot_provider_count() -> int:
    """Return total provider count."""
    registry = get_registry()
    if registry.configured:
        return registry.provider_count
    if pilot_settings.configured:
        return 1
    return 0
