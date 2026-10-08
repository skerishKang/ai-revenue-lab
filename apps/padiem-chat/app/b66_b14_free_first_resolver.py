from __future__ import annotations

"""B66's approved free-first selector over B14's existing trusted registry.

There is no new registry or provider connection here. Both fixed, bounded GETs
go through the existing B14 Service Binding. The caller supplies no model ID.
No provider inference/fallback occurs on failure or ambiguity.
"""

import json
from typing import Any, Protocol

from .b66_registered_model_boundary import (
    B14AuthorizedModelRoute,
    B66ModelRouteError,
    B66QuoteTaskRequirements,
)

_MODELS_PATH = "/api/pilot/models"
_READINESS_PATH = "/api/pilot/provider-readiness"
_OWNER_POLICY = "b66.quote.free-first.registered.v1"
_MAX_REGISTRY_BODY = 131072
_MAX_REGISTRY_ROWS = 256


def _excluded_by_owner(model_id: str) -> bool:
    """Refuse owner-excluded model families for B66's customer auto selection.

    These are exclusions, not replacement/model choice. Keep legacy B14 registry
    metadata unchanged until broader dependency and entitlement review.
    See #3554 and docs/operations/B14_OWNER_MODEL_DECISION_LEDGER_2026-10-08.md.
    """
    normalized = model_id.strip().casefold()
    return (
        "nemotron" in normalized  # NVIDIA Nemotron, all registered versions
        or (normalized.startswith("kilo/") and "poolside" in normalized and "laguna" in normalized)
        or (normalized.startswith("b-ai/") and "qwen" in normalized)
        or "motif-3" in normalized
        or "gpt-5.6-luna" in normalized
    )


class B14RegisteredModelView(Protocol):
    async def get_json(self, path: str) -> tuple[int, bytes]: ...


def _parse_bounded_response(status: object, raw: object) -> dict[str, Any]:
    if (
        type(status) is not int or status != 200 or not isinstance(raw, bytes)
        or len(raw) == 0 or len(raw) > _MAX_REGISTRY_BODY
    ):
        raise B66ModelRouteError("selection_unavailable")
    try:
        parsed = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise B66ModelRouteError("selection_unavailable") from None
    if not isinstance(parsed, dict):
        raise B66ModelRouteError("selection_unavailable")
    return parsed


def _dict_rows(value: object) -> list[dict[str, Any]]:
    if (
        not isinstance(value, list)
        or len(value) > _MAX_REGISTRY_ROWS
        or any(not isinstance(row, dict) for row in value)
    ):
        raise B66ModelRouteError("selection_unavailable")
    return value


def _qualified_routes(
    registry: dict[str, Any],
    readiness: dict[str, Any],
    requirements: B66QuoteTaskRequirements,
) -> list[B14AuthorizedModelRoute]:
    if readiness.get("provider_mode") != "live":
        raise B66ModelRouteError("selection_unavailable")
    routes = _dict_rows(registry.get("registered_routes"))
    catalog = _dict_rows(registry.get("catalog"))
    providers = _dict_rows(readiness.get("providers"))
    catalog_by_id: dict[str, dict[str, Any]] = {}
    providers_by_id: dict[str, dict[str, Any]] = {}
    for item in catalog:
        mid = item.get("id")
        if not isinstance(mid, str) or mid in catalog_by_id:
            raise B66ModelRouteError("selection_unavailable")
        catalog_by_id[mid] = item
    for item in providers:
        pid = item.get("provider_id")
        if not isinstance(pid, str) or pid in providers_by_id:
            raise B66ModelRouteError("selection_unavailable")
        providers_by_id[pid] = item

    qualified: list[B14AuthorizedModelRoute] = []
    seen: set[str] = set()
    for route in routes:
        mid = route.get("id")
        pid = route.get("provider_id")
        if not isinstance(mid, str) or not isinstance(pid, str) or mid in seen:
            raise B66ModelRouteError("selection_ambiguous")
        seen.add(mid)
        # Most recent owner exclusion overrides stale B14 registry/free metadata.
        # Never select these for B66 even when B14 marks them auto_eligible.
        if _excluded_by_owner(mid):
            continue
        # This policy is free-first and free-only until paid-budget authority
        # exists. Explicit-only/manual routes do not become automatic.
        if (
            route.get("free") is not True
            or route.get("auto_eligible") is not True
            or route.get("explicit_only") is not False
        ):
            continue
        info = catalog_by_id.get(mid)
        provider = providers_by_id.get(pid)
        if info is None or provider is None:
            continue
        if info.get("provider_id") != pid:
            continue
        tags = info.get("tags")
        if (
            not isinstance(tags, list)
            or not all(isinstance(tag, str) for tag in tags)
            or not requirements.required_capabilities.issubset(frozenset(tags))
            or "free" not in tags
        ):
            continue
        enabled_models = provider.get("models")
        if (
            not isinstance(enabled_models, list)
            or not all(isinstance(entry, str) for entry in enabled_models)
            or mid not in enabled_models
            or provider.get("enabled") is not True
            or provider.get("credential_ready") is not True
            or provider.get("route_ready") is not True
        ):
            continue
        qualified.append(B14AuthorizedModelRoute(
            model_id=mid,
            route_id=mid,  # B14 exact-ID registry; not a forged route alias
            owner_policy_id=_OWNER_POLICY,
            registered=True,
            enabled=True,
            authorized=True,
            credential_ready=True,
            route_count=1,
            capabilities=frozenset(tags),
        ))
    return qualified


class B14FreeFirstQuoteModelResolver:
    """B14 supplies all model and credential facts; B66 only applies policy."""

    def __init__(self, registry_transport: B14RegisteredModelView | None) -> None:
        self._transport = registry_transport

    async def resolve_quote_model(
        self, requirements: B66QuoteTaskRequirements
    ) -> B14AuthorizedModelRoute | None:
        if requirements != B66QuoteTaskRequirements():
            raise B66ModelRouteError("selection_unavailable")
        if self._transport is None:
            raise B66ModelRouteError("selection_unconfigured")
        try:
            registry_response = await self._transport.get_json(_MODELS_PATH)
            readiness_response = await self._transport.get_json(_READINESS_PATH)
            registry = _parse_bounded_response(*registry_response)
            readiness = _parse_bounded_response(*readiness_response)
            eligible = _qualified_routes(registry, readiness, requirements)
        except B66ModelRouteError:
            raise
        except Exception:
            raise B66ModelRouteError("selection_unavailable") from None
        if not eligible:
            raise B66ModelRouteError("selection_unavailable")
        if len(eligible) != 1:
            raise B66ModelRouteError("selection_ambiguous")
        return eligible[0]
