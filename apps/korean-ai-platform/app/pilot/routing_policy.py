"""Owner-designated fixed fallback chain for ``b14/auto`` (D14, #2044).

Owner decision 2026-09-07: ``b14/auto`` performs **no scorer-based automatic
routing**. It resolves to a fixed chain, in exactly this order:

  1. ``sensenova/sensenova-6.8-flash-lite``
  2. ``kilo/nvidia-nemotron-3-ultra-550b-a55b-free``
  3. ``kilo/minimax-minimax-m3-free``   (provisional until the Kilo benchmark)
  4. ``poolside/laguna-s-2.1``          (spare)

SenseNova leads the chain because the Kilo free routes carry a ~200 req/hour
budget. A chain position advances only on the existing fallback-allowed error
classes (``upstream_timeout`` / ``upstream_server_error`` /
``upstream_rate_limited`` — see ``router_core.is_error_fallback_allowed``).

Request options that the retired scorer consumed (``task_type``,
``required_capabilities``, ``optimize_for``, ``provider_order``,
``allow_paid``) remain accepted by the gateway for API compatibility but do
NOT change chain selection; their names are recorded in ``reason_codes`` as
``ignored_options:...``. ``allow_external_fallback`` and ``max_attempts``
still bound the attempt count.

A chain model that is missing from the catalog registry, or disabled, is a
deployment defect: :func:`chain_models` fails closed with
``RoutingError("routing_policy_invalid")``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.pilot.b14_runtime_config import runtime_config
from app.pilot.catalog import CatalogModel, get_catalog_by_id
from app.pilot.errors import NoSafeRoute, RoutingError
from app.pilot.kilo_provider import (
    KILO_MINIMAX_M3_MODEL_ID,
    KILO_NEMOTRON_MODEL_ID,
)
from app.pilot.poolside_provider import POOLSIDE_MODEL_ID
from app.pilot.router_core import (
    EvidenceStatus,
    RouteDecision,
    RouteMode,
    _credential_status_for,
    _new_request_id,
    _platform_secret_present,
)
from app.pilot.sensenova_provider import SENSENOVA_MODEL_ID

ROUTING_POLICY_ID = "fixed_chain_v1"

B14_AUTO_CHAIN: tuple[str, ...] = (
    SENSENOVA_MODEL_ID,
    KILO_NEMOTRON_MODEL_ID,
    KILO_MINIMAX_M3_MODEL_ID,
    POOLSIDE_MODEL_ID,
)

MAX_CHAIN_ATTEMPTS = len(B14_AUTO_CHAIN)

# Scorer-era options that the fixed chain accepts but never consults.
_IGNORED_OPTION_KEYS = frozenset({
    "task_type",
    "required_capabilities",
    "optimize_for",
    "provider_order",
    "allow_paid",
})


def chain_models() -> list[CatalogModel]:
    """Return the catalog entries for the fixed chain, in chain order.

    Raises RoutingError("routing_policy_invalid") if any chain model is not
    registered in the catalog or is disabled (fail closed: the chain is
    owner-designated configuration, not a caller input).
    """
    models: list[CatalogModel] = []
    for model_id in B14_AUTO_CHAIN:
        cm = get_catalog_by_id(model_id)
        if cm is None:
            raise RoutingError(
                code="routing_policy_invalid",
                message=(
                    f"fixed chain model '{model_id}' is not registered in the catalog."
                ),
            )
        if not cm.enabled:
            raise RoutingError(
                code="routing_policy_invalid",
                message=f"fixed chain model '{model_id}' is disabled.",
            )
        models.append(cm)
    return models


def resolve_chain_route(
    allow_external_fallback: bool = True,
    max_attempts: int | None = None,
    requested_options: Mapping[str, Any] | None = None,
) -> RouteDecision:
    """Resolve ``b14/auto`` through the owner-designated fixed chain.

    Deterministic selection: the first chain position whose platform secret
    is present. Does NOT make upstream calls. Chain candidates excluded for a
    missing secret are reported in ``excluded_candidates`` with reason
    ``provider_secret_missing``. If no chain position has a usable
    credential, raises NoSafeRoute (no upstream call made).
    """
    request_id = _new_request_id()
    models = chain_models()

    excluded: list[dict[str, str]] = []
    candidates: list[CatalogModel] = []
    for m in models:
        if m.credential_source == "platform_secret" and not _platform_secret_present(m):
            excluded.append({
                "model_id": m.model_id,
                "upstream_model": m.upstream_model,
                "provider": m.provider,
                "reason": "provider_secret_missing",
            })
            continue
        candidates.append(m)

    if not candidates:
        raise NoSafeRoute(
            reason_code="no_chain_candidate_available",
            message=(
                "b14/auto fixed chain has no candidate with a usable credential."
            ),
            upstream_called=False,
        )

    selected = candidates[0]
    cred_ok, cred_status, cred_source, plat_pid = _credential_status_for(selected)
    route_id = f"platform:{selected.model_id}"

    if allow_external_fallback:
        fallback_candidates = [
            {
                "model_id": m.model_id,
                "upstream_model": m.upstream_model,
                "provider": m.provider,
                "route_id": f"platform:{m.model_id}",
                "reason": "fixed_chain_fallback",
                "platform_provider_id": m.platform_provider_id or "",
            }
            for m in candidates[1:]
        ]
        bound = len(candidates)
        if max_attempts is not None:
            bound = min(bound, max(int(max_attempts), 1))
        effective_max_attempts = min(bound, MAX_CHAIN_ATTEMPTS)
    else:
        fallback_candidates = []
        effective_max_attempts = 1

    reason_codes = [
        f"routing_policy:{ROUTING_POLICY_ID}",
        "chain_position:1",
        f"selected:{selected.model_id}",
    ]
    ignored = sorted(
        key for key in (requested_options or {}) if key in _IGNORED_OPTION_KEYS
    )
    if ignored:
        reason_codes.append(f"ignored_options:{','.join(ignored)}")
    if not allow_external_fallback:
        reason_codes.append("external_fallback_disabled")

    return RouteDecision(
        route_mode=RouteMode.AUTO.value,
        selected_provider=selected.provider,
        selected_model=selected.model_id,
        selected_upstream_model=selected.upstream_model,
        selected_route_id=route_id,
        reason_codes=reason_codes,
        fallback_allowed=allow_external_fallback,
        eligible_fallback=fallback_candidates,
        excluded_candidates=excluded,
        credential_available=cred_ok,
        credential_status=cred_status,
        evidence_status=EvidenceStatus.RESOLVED_NOT_CALLED.value,
        request_id=request_id,
        provider_mode=runtime_config.provider_mode,
        max_attempts=effective_max_attempts,
        credential_source=cred_source,
        platform_provider_id=plat_pid,
    )
