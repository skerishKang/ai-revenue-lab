"""Trusted execution-target join for canonical Business 14 registry-v2 routes.

This module prepares the runtime migration boundary without switching the
active Router Core.  Canonical registry v2 owns public-model and route identity;
the existing legacy Provider registry remains the trusted server-side transport
configuration for base URL and timeout in this slice.

Important boundaries:
- callers resolve by globally unique ``route_id`` rather than public ``model_id``;
- canonical route identity is projected from the exact same legacy source first;
- Provider transport configuration is joined only after exact provider/model/
  upstream correlation;
- credentials, account, entitlement and billing state are not represented here;
- no Provider call or active routing mutation occurs in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from app.pilot.registry_v2 import RegistryV2Error
from app.pilot.registry_v2_legacy import legacy_registry_json_to_v2


class RegistryV2ExecutionError(ValueError):
    """Bounded fail-closed error for registry-v2 execution-target resolution."""

    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


@dataclass(frozen=True, slots=True)
class CanonicalRouteExecutionTarget:
    """Trusted server-only transport target for one canonical route identity."""

    route_id: str
    provider_id: str
    provider_name: str
    model_id: str
    upstream_model: str
    base_url: str
    timeout_seconds: int


def _parse_validated_legacy_source(raw_json: str) -> list[dict[str, Any]]:
    """Return the strict legacy source after canonical projection validation."""

    try:
        payload = json.loads(raw_json)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RegistryV2ExecutionError(
            "invalid_legacy_registry",
            "legacy Provider registry is invalid",
        ) from exc
    if not isinstance(payload, list):
        raise RegistryV2ExecutionError(
            "invalid_legacy_registry",
            "legacy Provider registry is invalid",
        )
    return payload


def resolve_legacy_v2_route_execution_target(
    raw_json: str,
    route_id: str,
) -> CanonicalRouteExecutionTarget:
    """Resolve one canonical route ID to trusted legacy transport configuration.

    The canonical registry is derived from ``raw_json`` first, which means the
    route identity and transport data must originate from the same accepted
    legacy registry source.  Public ``model_id`` is intentionally not accepted
    as an execution selector here because registry v2 permits multiple Provider
    routes per public model.
    """

    if not isinstance(route_id, str) or not route_id.strip():
        raise RegistryV2ExecutionError(
            "invalid_route_id",
            "route_id must be a non-empty canonical route reference",
        )

    try:
        registry = legacy_registry_json_to_v2(raw_json)
    except RegistryV2Error as exc:
        raise RegistryV2ExecutionError(exc.code, exc.safe_message) from exc

    route = registry.get_route(route_id.strip())
    if route is None:
        raise RegistryV2ExecutionError(
            "route_not_found",
            "canonical Provider route was not found",
        )
    if not route.enabled:
        raise RegistryV2ExecutionError(
            "route_disabled",
            "canonical Provider route is disabled",
        )

    payload = _parse_validated_legacy_source(raw_json)
    provider_raw = next(
        (
            item
            for item in payload
            if isinstance(item, dict) and item.get("provider_id") == route.provider_id
        ),
        None,
    )
    if provider_raw is None:
        raise RegistryV2ExecutionError(
            "route_source_mismatch",
            "canonical route Provider does not match trusted transport configuration",
        )

    raw_models = provider_raw.get("models")
    if not isinstance(raw_models, list):
        raise RegistryV2ExecutionError(
            "route_source_mismatch",
            "canonical route model does not match trusted transport configuration",
        )
    model_raw = next(
        (
            item
            for item in raw_models
            if isinstance(item, dict)
            and item.get("model_id") == route.model_id
            and item.get("upstream_model") == route.upstream_model
        ),
        None,
    )
    if model_raw is None:
        raise RegistryV2ExecutionError(
            "route_source_mismatch",
            "canonical route model does not match trusted transport configuration",
        )
    if model_raw.get("enabled", True) is not True:
        raise RegistryV2ExecutionError(
            "route_disabled",
            "canonical Provider route is disabled",
        )

    provider_name = provider_raw.get("display_name") or route.provider_id
    base_url = provider_raw.get("base_url")
    timeout_seconds = provider_raw.get("timeout_seconds", 30)

    # The legacy parser already validated these fields before registry-v2
    # projection.  Keep defensive type checks here so this seam remains safe if
    # that implementation is later refactored.
    if not isinstance(provider_name, str) or not provider_name.strip():
        raise RegistryV2ExecutionError(
            "route_source_mismatch",
            "trusted Provider display metadata is invalid",
        )
    if not isinstance(base_url, str) or not base_url.strip():
        raise RegistryV2ExecutionError(
            "route_source_mismatch",
            "trusted Provider transport URL is invalid",
        )
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int):
        raise RegistryV2ExecutionError(
            "route_source_mismatch",
            "trusted Provider timeout configuration is invalid",
        )

    return CanonicalRouteExecutionTarget(
        route_id=route.route_id,
        provider_id=route.provider_id,
        provider_name=provider_name.strip(),
        model_id=route.model_id,
        upstream_model=route.upstream_model,
        base_url=base_url.strip(),
        timeout_seconds=timeout_seconds,
    )
