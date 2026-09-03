"""Fail-closed projection from the Phase-2 Provider registry into registry v2.

The legacy registry remains the active runtime configuration in this slice.
This adapter exists only to make migration semantics explicit and testable.
It does not select routes, resolve credentials, or mutate Production state.

Truth-preservation rules:
- the legacy parser is authoritative for whether the source registry is valid;
- legacy public HTTPS Provider routes may be classified as ``external``;
- legacy configuration has no authoritative region, context-window, or
  max-output metadata, so those values remain explicitly unknown;
- unknown legacy extension fields fail closed instead of silently crossing
  the registry-v2 boundary;
- Provider base URLs/timeouts are execution configuration and are not emitted
  by the public registry-v2 projection.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.pilot.registry import ProviderRegistry
from app.pilot.registry_v2 import (
    CanonicalRegistryV2,
    ProviderDefinition,
    ProviderRouteDefinition,
    PublicModelDefinition,
    RegistryV2Error,
    RouteClass,
)

LEGACY_UNKNOWN_REGION = "unknown"

_PROVIDER_FIELDS = frozenset(
    {"provider_id", "display_name", "base_url", "timeout_seconds", "models"}
)
_MODEL_FIELDS = frozenset(
    {"model_id", "upstream_model", "display_name", "enabled"}
)


def _reject_unknown_fields(
    *,
    value: dict[str, Any],
    allowed: frozenset[str],
    subject: str,
) -> None:
    if set(value) - allowed:
        raise RegistryV2Error(
            "unsafe_legacy_registry_extension",
            f"{subject} contains fields that are not part of the accepted legacy registry contract",
        )


def _legacy_route_id(provider_id: str, model_id: str) -> str:
    """Return a stable bounded route identity for one legacy provider/model pair."""

    digest = hashlib.sha256(
        f"{provider_id}\x00{model_id}".encode("utf-8")
    ).hexdigest()[:32]
    return f"legacy:{provider_id}:{digest}"


def legacy_registry_json_to_v2(raw_json: str) -> CanonicalRegistryV2:
    """Project validated legacy registry JSON into the canonical registry-v2 model.

    The current Phase-2 registry requires globally unique ``model_id`` values,
    so a migrated legacy model initially has exactly one route.  Registry v2
    itself permits additional Provider routes for that same public model later.

    No capability, cost, latency, quality, entitlement, geography, context, or
    output-limit facts are inferred here.
    """

    if not isinstance(raw_json, str) or not raw_json.strip():
        raise RegistryV2Error(
            "legacy_registry_not_configured",
            "legacy registry JSON must be a non-empty string",
        )

    legacy = ProviderRegistry(raw_json)
    if legacy.parse_error is not None or not legacy.configured:
        raise RegistryV2Error(
            "invalid_legacy_registry",
            "legacy Provider registry is invalid",
        )

    # Re-read only after the existing legacy parser has accepted the source.
    # This second pass is intentionally strict about extension fields so
    # credentials/account state cannot silently cross into registry v2.
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError as exc:  # defensive; legacy parser already checked
        raise RegistryV2Error(
            "invalid_legacy_registry",
            "legacy Provider registry is invalid",
        ) from exc

    providers: list[ProviderDefinition] = []
    models: list[PublicModelDefinition] = []
    routes: list[ProviderRouteDefinition] = []

    for provider_index, raw_provider in enumerate(payload):
        if not isinstance(raw_provider, dict):
            raise RegistryV2Error(
                "invalid_legacy_registry",
                "legacy Provider registry is invalid",
            )
        _reject_unknown_fields(
            value=raw_provider,
            allowed=_PROVIDER_FIELDS,
            subject=f"provider[{provider_index}]",
        )

        provider_id = raw_provider["provider_id"].strip()
        provider_display_name = (
            raw_provider.get("display_name") or provider_id
        ).strip()
        providers.append(
            ProviderDefinition(
                provider_id=provider_id,
                display_name=provider_display_name,
            )
        )

        for model_index, raw_model in enumerate(raw_provider["models"]):
            if not isinstance(raw_model, dict):
                raise RegistryV2Error(
                    "invalid_legacy_registry",
                    "legacy Provider registry is invalid",
                )
            _reject_unknown_fields(
                value=raw_model,
                allowed=_MODEL_FIELDS,
                subject=f"provider[{provider_index}].model[{model_index}]",
            )

            model_id = raw_model["model_id"].strip()
            upstream_model = raw_model["upstream_model"].strip()
            display_name = (raw_model.get("display_name") or model_id).strip()
            enabled = raw_model.get("enabled", True)

            models.append(
                PublicModelDefinition(
                    model_id=model_id,
                    display_name=display_name,
                    context_window=None,
                    max_output_tokens=None,
                )
            )
            routes.append(
                ProviderRouteDefinition(
                    route_id=_legacy_route_id(provider_id, model_id),
                    model_id=model_id,
                    provider_id=provider_id,
                    upstream_model=upstream_model,
                    enabled=enabled,
                    route_class=RouteClass.EXTERNAL,
                    region=LEGACY_UNKNOWN_REGION,
                )
            )

    return CanonicalRegistryV2(
        providers=tuple(providers),
        models=tuple(models),
        routes=tuple(routes),
    )
