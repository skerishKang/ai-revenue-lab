"""Configuration state resolver and model routing for BYOK Gateway Pilot.

Responsibility boundary:
- PilotConfigurationState: explicit enum for all config states
- resolve_configuration(): single source of truth for what state the pilot is in
- resolve_route(): model_id → RouteTarget with proper error handling

This module replaces ad-hoc state checks spread across config.py, gateway.py,
and registry.py with a single deterministic resolver.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass

from app.pilot.config import pilot_settings
from app.pilot.registry import get_registry
from app.pilot.errors import (
    RegistryInvalid,
    PilotNotConfigured,
    ModelNotFound,
    ModelDisabled,
    AmbiguousModelRoute,
)

logger = logging.getLogger("korean-ai-platform.pilot")


class PilotConfigurationState(str, enum.Enum):
    """Explicit, mutually exclusive configuration states."""

    VALID_REGISTRY = "valid_registry"
    INVALID_REGISTRY = "invalid_registry"
    LEGACY = "legacy"
    NOT_CONFIGURED = "not_configured"


@dataclass(frozen=True)
class RouteTarget:
    """Resolved routing target for a single provider call."""

    provider_id: str
    provider_name: str
    model_id: str
    upstream_model: str
    base_url: str
    timeout_seconds: int


def resolve_configuration() -> PilotConfigurationState:
    """Determine the current pilot configuration state.

    Resolution order:
    1. Registry JSON present → check registry validity
       a. registry.parse_error exists → INVALID_REGISTRY (fail-closed)
       b. registry.configured → VALID_REGISTRY
    2. Legacy single-provider env vars → LEGACY
    3. Nothing → NOT_CONFIGURED

    Invalid registry NEVER falls back to legacy.
    """
    if pilot_settings.has_registry:
        registry = get_registry()
        if registry.parse_error is not None:
            return PilotConfigurationState.INVALID_REGISTRY
        if registry.configured:
            return PilotConfigurationState.VALID_REGISTRY
        # Registry JSON present but somehow not configured -> still invalid
        return PilotConfigurationState.INVALID_REGISTRY

    if pilot_settings.has_legacy:
        return PilotConfigurationState.LEGACY

    return PilotConfigurationState.NOT_CONFIGURED


def resolve_route(model_id: str) -> RouteTarget:
    """Resolve a model ID to a RouteTarget, raising on error.

    Must only be called when configuration is VALID_REGISTRY or LEGACY.
    Raises PilotError subclasses for all failure modes.

    Returns:
        RouteTarget for the given model ID

    Raises:
        PilotNotConfigured: no configuration at all
        RegistryInvalid: registry present but invalid (should not happen if caller
                         checks state first, but safely handled here too)
        ModelNotFound: model ID not found
        ModelDisabled: model ID exists but is disabled
        AmbiguousModelRoute: model resolves to multiple providers (should not
                             happen since registry prevents duplicates)
    """
    state = resolve_configuration()

    if state == PilotConfigurationState.NOT_CONFIGURED:
        raise PilotNotConfigured()

    if state == PilotConfigurationState.INVALID_REGISTRY:
        registry = get_registry()
        detail = registry.parse_error or "Provider registry 설정이 올바르지 않습니다."
        raise RegistryInvalid(detail=detail)

    if state == PilotConfigurationState.VALID_REGISTRY:
        registry = get_registry()
        if registry.is_model_disabled(model_id):
            raise ModelDisabled(model_id)
        route = registry.get_model(model_id)
        if route is None:
            raise ModelNotFound(model_id)
        return route

    # LEGACY mode - backward compatible: use UnsupportedModel for Phase 1 compat
    if model_id != pilot_settings.pilot_model_id:
        if pilot_settings.pilot_upstream_model and model_id == pilot_settings.pilot_upstream_model:
            pass
        else:
            from app.pilot.errors import UnsupportedModel
            raise UnsupportedModel(model_id)

    upstream = pilot_settings.pilot_upstream_model or pilot_settings.pilot_model_id
    return RouteTarget(
        provider_id=pilot_settings.pilot_provider_id,
        provider_name=pilot_settings.pilot_provider_id.replace("-", " ").title(),
        model_id=pilot_settings.pilot_model_id,
        upstream_model=upstream,
        base_url=pilot_settings.pilot_base_url,
        timeout_seconds=pilot_settings.pilot_timeout_seconds,
    )


def require_configured() -> None:
    """Raise PilotNotConfigured if the pilot has no valid configuration."""
    state = resolve_configuration()
    if state in (PilotConfigurationState.NOT_CONFIGURED, PilotConfigurationState.INVALID_REGISTRY):
        if state == PilotConfigurationState.INVALID_REGISTRY:
            registry = get_registry()
            raise RegistryInvalid(detail=registry.parse_error or "Provider registry 설정이 올바르지 않습니다.")
        raise PilotNotConfigured()
