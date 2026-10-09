from __future__ import annotations

"""B66 owner-allowed registered-model selector over B14's trusted registry.

The historical file/class names are preserved for import compatibility; their
old free-first qualification is retired by the B66 owner price-filter decision.
Only two fixed, bounded GETs traverse B14's existing Service Binding, with no
untrusted model information inside quote text. Selection requires a distinct
explicit model_id from the authenticated user; no implicit default or fallback.
"""

import json
import re
from dataclasses import replace
from typing import Any, Protocol

from .b66_registered_model_boundary import (
    B14AuthorizedModelRoute,
    B66ModelRouteError,
    B66QuoteTaskRequirements,
)

_MODELS_PATH = "/api/pilot/models"
_READINESS_PATH = "/api/pilot/provider-readiness"
_OWNER_POLICY = "OWNER_REGISTERED_AND_ALLOWED"
_MAX_REGISTRY_BODY = 131072
_MAX_REGISTRY_ROWS = 256
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}\Z")


def _excluded_by_owner(model_id: str) -> bool:
    """Refuse owner-excluded model families for B66's product-specific selection.

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
        if requirements.selected_model_id is not None and mid != requirements.selected_model_id:
            continue
        # Both the local owner exclusion and B14's explicit exclusion claim
        # must permit the exact route. Missing owner_excluded fails closed.
        if _excluded_by_owner(mid) or route.get("owner_excluded") is not False:
            continue
        # B14 free/public/auto_eligible/explicit_only flags belong to its
        # general-purpose auto router. They are NOT B66 eligibility gates.
        # B66 can use a paid or manual-pin registered route ONLY when the
        # exact route is owner-allowed, chat-capable and live-ready; two such
        # candidates remain ambiguous and must not be auto-ranked.
        info = catalog_by_id.get(mid)
        provider = providers_by_id.get(pid)
        if provider is None:
            continue
        # Display catalog omits manual-pin registrations; consume exact
        # capabilities attested in the trusted B14 registered-route record.
        # A present display summary must not contradict the provider.
        if info is not None and info.get("provider_id") != pid:
            continue
        tags = route.get("capabilities")
        if (
            not isinstance(tags, list)
            or not all(isinstance(tag, str) for tag in tags)
            or not requirements.required_capabilities.issubset(frozenset(tags))
        ):
            continue
        if info is not None:
            summary_tags = info.get("tags")
            if (
                not isinstance(summary_tags, list)
                or not all(isinstance(tag, str) for tag in summary_tags)
                or not requirements.required_capabilities.issubset(frozenset(summary_tags))
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
    """B14 supplies registration and readiness; B66 applies owner eligibility.

    This compatibility class retains its old import name without the old
    free-first behavior. No generic B14 auto-route flags are modified.
    """

    def __init__(self, registry_transport: B14RegisteredModelView | None) -> None:
        self._transport = registry_transport

    async def resolve_quote_model(
        self, requirements: B66QuoteTaskRequirements
    ) -> B14AuthorizedModelRoute | None:
        if not isinstance(requirements.selected_model_id, str) or not _SAFE_ID.fullmatch(requirements.selected_model_id):
            raise B66ModelRouteError("selection_unconfigured")
        if replace(requirements, selected_model_id=None) != B66QuoteTaskRequirements():
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

    async def list_selectable_models(self) -> list[dict[str, str]]:
        """Authenticated B66 UI options only; 2 fixed GETs, zero provider POSTs.

        Only owner-permitted, ready chat routes are offered; the API never
        chooses a model or returns a secret, provider URL, or price metadata.
        """
        if self._transport is None:
            raise B66ModelRouteError("selection_unconfigured")
        try:
            registry = _parse_bounded_response(*await self._transport.get_json(_MODELS_PATH))
            readiness = _parse_bounded_response(*await self._transport.get_json(_READINESS_PATH))
            routes = _qualified_routes(registry, readiness, B66QuoteTaskRequirements())
        except B66ModelRouteError:
            raise
        except Exception:
            raise B66ModelRouteError("selection_unavailable") from None
        ids = [row.model_id for row in routes]
        if len(ids) != len(set(ids)):
            raise B66ModelRouteError("selection_ambiguous")
        return [
            {"model_id": row.model_id, "name": row.model_id.split("/")[-1]}
            for row in sorted(routes, key=lambda row: row.model_id)
        ]


class B66ExplicitQuoteModelResolver(B14FreeFirstQuoteModelResolver):
    """Preferred B66 owner-authorized, user-selected registered model resolver.

    The former class name is retained solely for existing source imports/tests.
    Its previous free-first/automatic behavior is no longer implemented.
    """
