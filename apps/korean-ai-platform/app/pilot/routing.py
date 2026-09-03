"""Configuration state resolver and model routing for BYOK Gateway Pilot.

Responsibility boundary:
- PilotConfigurationState: explicit enum for all config states
- resolve_configuration(): single source of truth for what state the pilot is in
- resolve_route(): public model_id -> trusted RouteTarget with proper error handling

For a configured multi-provider registry, public model identity is preserved for
request compatibility, but final transport authority is resolved through the
canonical registry-v2 ``route_id`` seam before a RouteTarget is returned.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass

from app.pilot.config import pilot_settings
from app.pilot.registry import get_registry
from app.pilot.errors import (
    AmbiguousModelRoute,
    RegistryInvalid,
    PilotNotConfigured,
    ModelNotFound,
    ModelDisabled,
    UnsupportedModel,
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
    1. Registry JSON present -> check registry validity
       a. registry.parse_error exists -> INVALID_REGISTRY (fail-closed)
       b. registry.configured -> VALID_REGISTRY
    2. Legacy single-provider env vars -> LEGACY
    3. Nothing -> NOT_CONFIGURED

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


def _resolve_registry_v2_transport(model_id: str) -> RouteTarget:
    """Resolve a VALID_REGISTRY public model through canonical route identity.

    Imports are intentionally local. ``registry_v2_legacy`` validates through
    the existing ProviderRegistry, which imports RouteTarget from this module;
    keeping the migration imports lazy avoids a module initialization cycle.
    """

    registry = get_registry()
    if registry.is_model_disabled(model_id):
        raise ModelDisabled(model_id)
    if registry.get_model(model_id) is None:
        raise ModelNotFound(model_id)

    from app.pilot.registry_v2 import RegistryV2Error
    from app.pilot.registry_v2_execution import (
        RegistryV2ExecutionError,
        resolve_legacy_v2_route_execution_target,
    )
    from app.pilot.registry_v2_legacy import legacy_registry_json_to_v2

    raw_json = pilot_settings.provider_registry_json
    try:
        canonical_registry = legacy_registry_json_to_v2(raw_json)
        canonical_model = canonical_registry.get_model(model_id)
        if canonical_model is None:
            raise ModelNotFound(model_id)

        all_routes = canonical_registry.routes_for_model(model_id, enabled_only=False)
        enabled_routes = tuple(route for route in all_routes if route.enabled)
        if not enabled_routes:
            if all_routes:
                raise ModelDisabled(model_id)
            raise ModelNotFound(model_id)
        if len(enabled_routes) != 1:
            raise AmbiguousModelRoute(model_id)

        execution_target = resolve_legacy_v2_route_execution_target(
            raw_json,
            enabled_routes[0].route_id,
        )
    except (ModelNotFound, ModelDisabled, AmbiguousModelRoute):
        raise
    except (RegistryV2Error, RegistryV2ExecutionError) as exc:
        logger.warning(
            "Canonical registry-v2 execution resolution failed closed: %s",
            exc.code,
        )
        raise RegistryInvalid(
            detail="Provider registry 설정이 올바르지 않습니다."
        ) from exc

    if execution_target.model_id != model_id:
        raise RegistryInvalid(
            detail="Provider registry 설정이 올바르지 않습니다."
        )

    return RouteTarget(
        provider_id=execution_target.provider_id,
        provider_name=execution_target.provider_name,
        model_id=execution_target.model_id,
        upstream_model=execution_target.upstream_model,
        base_url=execution_target.base_url,
        timeout_seconds=execution_target.timeout_seconds,
    )


def resolve_route(model_id: str) -> RouteTarget:
    """Resolve a model ID to a RouteTarget, raising on error.

    Must only be called when configuration is VALID_REGISTRY or LEGACY.
    Raises PilotError subclasses for all failure modes.

    In VALID_REGISTRY mode, ``model_id`` remains the public compatibility input,
    while final transport selection is authorized by exactly one canonical
    registry-v2 route ID derived from the same trusted registry source.

    Returns:
        RouteTarget for the given model ID

    Raises:
        PilotNotConfigured: no configuration at all
        RegistryInvalid: registry present but invalid or canonical execution
                         identity cannot be correlated safely
        ModelNotFound: model ID not found
        ModelDisabled: model ID exists but is disabled
        AmbiguousModelRoute: model resolves to multiple enabled canonical routes
    """
    state = resolve_configuration()

    if state == PilotConfigurationState.NOT_CONFIGURED:
        raise PilotNotConfigured()

    if state == PilotConfigurationState.INVALID_REGISTRY:
        raise RegistryInvalid(detail="Provider registry 설정이 올바르지 않습니다.")

    if state == PilotConfigurationState.VALID_REGISTRY:
        return _resolve_registry_v2_transport(model_id)

    # LEGACY mode - backward compatible: use UnsupportedModel for Phase 1 compat
    if model_id != pilot_settings.pilot_model_id:
        if pilot_settings.pilot_upstream_model and model_id == pilot_settings.pilot_upstream_model:
            pass
        else:
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
