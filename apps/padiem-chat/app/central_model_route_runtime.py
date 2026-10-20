"""#4428: read central product/tier routes at the product selection point.

The product resolves one exact B14 model before dispatch. B14 remains the final
catalog/credential/execution authority. Failure policy is deliberate:

* no store configured, no row, or a D1 read failure -> the historical static
  product contract, never a wider model set;
* an explicit disabled row -> fail closed;
* an explicit primary/fallback -> only those two exact models are candidates.

No provider connection, credential or B14 registry mutation happens here.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from starlette.requests import Request

from padiem_control_plane.model_assignment_policy import (
    ModelPolicySnapshot,
    TIERS,
    product_scope_set,
)
from padiem_control_plane.model_tier_routes import (
    TierRouteResolution,
    TierRouteSnapshot,
    effective_tier_route,
    static_tier_route,
)
from padiem_control_plane.product_tier_routes import (
    FREE_FALLBACK_B14_MODEL_ID,
    ProductTierLabel,
    ProductTierRoutesError,
    active_route_for,
)

from .model_policy import (
    FREE_B14_MODEL_ID,
    ModelPolicyError,
    request_tier_context,
)

WORKSPACE = "padiem-global"
_TIER_BY_ID = {
    "free": "FREE",
    "plus": "PLUS",
    "pro": "PRO",
    "max": "MAX",
}
_LABEL_BY_ID = {
    "free": ProductTierLabel.FREE,
    "plus": ProductTierLabel.PLUS,
    "pro": ProductTierLabel.PRO,
    "max": ProductTierLabel.MAX,
}


class CentralRouteUnavailable(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _store(request: Request):
    return getattr(request.app.state, "central_model_route_store", None)


async def _blocked_models_from_store(
    store: object, product: str, tier: str,
) -> frozenset[str]:
    """Existing allow/block rows stay advisory except for explicit blocks.

    Runtime route selection reads blocks so an operator's explicit block is
    never silently routed around. A policy read failure imposes no extra
    restriction: only the already validated central route remains in force.

    #2505: the Chat and Claw surfaces share one grade setting, so a block on
    either screen of the shared product blocks the shared setting for both.
    """
    read = getattr(store, "snapshot", None)
    if not callable(read):
        return frozenset()
    try:
        value = read(WORKSPACE)
        snapshot = await value if hasattr(value, "__await__") else value
    except Exception:
        return frozenset()
    if not isinstance(snapshot, ModelPolicySnapshot) or snapshot.workspace_id != WORKSPACE:
        return frozenset()
    blocked_scope = frozenset({"central"}) | product_scope_set(product)
    return frozenset(
        rule.model_id for rule in snapshot.rules
        if rule.action == "block" and rule.tier == tier and rule.product in blocked_scope
    )


async def _read_route_snapshot(route_store: object) -> object | None:
    """Read the applied route ledger once.

    ``None`` means "no ledger could be read": no store is configured, the
    migration is not applied, or D1 is unavailable. The caller then keeps the
    historical static product contract instead of taking the product offline.
    """
    read = getattr(route_store, "snapshot", None)
    if not callable(read):
        return None
    try:
        value = read(WORKSPACE)
        return await value if hasattr(value, "__await__") else value
    except Exception:
        return None


def _applied_revision(snapshot: object) -> int:
    """Ledger revision of this workspace read, 0 when there is no ledger."""
    if isinstance(snapshot, TierRouteSnapshot) and snapshot.workspace_id == WORKSPACE:
        return snapshot.revision
    return 0


async def resolve_tier_route_view_from_stores(
    route_store: object,
    policy_store: object,
    *,
    product: str,
    tier: str,
    static_primary: str | None,
    static_fallback: str | None = None,
) -> tuple[TierRouteResolution, int]:
    """Store-based resolver plus the applied ledger revision (one read).

    The revision is the ledger revision of the stored row that governs this
    product/tier. A grade that no stored row governs reports 0, so a reader
    never mistakes an unrelated ledger revision for an applied decision.
    """
    if tier not in TIERS:
        raise ValueError("invalid route tier")
    # The policy ledger is independent of the route ledger. A route read
    # outage must not silently remove a policy block that remains readable.
    blocked_model_ids = await _blocked_models_from_store(policy_store, product, tier)
    snapshot = await _read_route_snapshot(route_store)
    if snapshot is None:
        return static_tier_route(
            static_primary, static_fallback, blocked_model_ids=blocked_model_ids,
        ), 0
    resolution = effective_tier_route(
        snapshot,
        workspace_id=WORKSPACE,
        product=product,
        tier=tier,
        static_primary=static_primary,
        static_fallback=static_fallback,
        blocked_model_ids=blocked_model_ids,
    )
    revision = _applied_revision(snapshot) if resolution.source == "central" else 0
    return resolution, revision


async def resolve_tier_route_from_stores(
    route_store: object,
    policy_store: object,
    *,
    product: str,
    tier: str,
    static_primary: str | None,
    static_fallback: str | None = None,
) -> TierRouteResolution:
    """Store-based resolver for callers that have no HTTP Request (cron)."""
    resolution, _revision = await resolve_tier_route_view_from_stores(
        route_store,
        policy_store,
        product=product,
        tier=tier,
        static_primary=static_primary,
        static_fallback=static_fallback,
    )
    return resolution


async def resolve_tier_route(
    request: Request,
    *,
    product: str,
    tier: str,
    static_primary: str | None,
    static_fallback: str | None = None,
) -> TierRouteResolution:
    return await resolve_tier_route_from_stores(
        _store(request),
        getattr(request.app.state, "central_model_policy_store", None),
        product=product,
        tier=tier,
        static_primary=static_primary,
        static_fallback=static_fallback,
    )


def _static_chat_route(tier_id: str) -> tuple[str | None, str | None]:
    if tier_id == "free":
        return FREE_B14_MODEL_ID, FREE_FALLBACK_B14_MODEL_ID
    label = _LABEL_BY_ID[tier_id]
    try:
        route = active_route_for(label)
    except ProductTierRoutesError:
        return None, None
    return (route.model_id if route is not None else None), None


async def resolve_chat_tier_route(request: Request, tier_id: str) -> TierRouteResolution:
    static_primary, static_fallback = _static_chat_route(tier_id)
    return await resolve_tier_route(
        request, product="chat", tier=_TIER_BY_ID[tier_id],
        static_primary=static_primary, static_fallback=static_fallback,
    )


@asynccontextmanager
async def chat_request_tier_context(request: Request, tier_id: str):
    """Resolve a centrally assigned Chat model, then bind the request tier.

    ``admin`` is a separate verified administrator lane and never a product
    grade route; it keeps the existing exact administrator model.
    """
    if tier_id is None:
        # Preserve the pre-existing "no tier binding" request shape.
        with request_tier_context(None):
            yield
        return
    if not isinstance(tier_id, str):
        raise ModelPolicyError("unknown_product_tier", "지원하지 않는 AI 등급입니다.")
    normalized = tier_id.strip().lower()
    if normalized == "admin":
        with request_tier_context("admin"):
            yield
        return
    if normalized not in _TIER_BY_ID:
        raise ModelPolicyError("unknown_product_tier", "지원하지 않는 AI 등급입니다.")
    resolution = await resolve_chat_tier_route(request, normalized)
    if not resolution.ok or resolution.model_id is None:
        raise ModelPolicyError(
            "tier_unavailable",
            "선택한 AI 등급은 현재 준비 중입니다. 다른 등급을 선택해 주세요.",
        )
    with request_tier_context(normalized, model_id=resolution.model_id):
        yield


async def resolve_claw_tier_model_view_from_stores(
    route_store: object, policy_store: object, tier_id: str,
) -> tuple[TierRouteResolution, int]:
    """Resolve the Claw grade route and report the applied ledger revision.

    The revision lets a product read path state which applied central route it
    is serving, so an operator can tell an applied decision from the static
    declaration without reading the admin ledger separately.
    """
    label = _LABEL_BY_ID.get(tier_id)
    if label is None:
        raise ValueError("invalid Claw tier")
    static_primary: str | None = None
    static_fallback: str | None = None
    try:
        route = active_route_for(label)
        static_primary = route.model_id if route is not None else None
    except ProductTierRoutesError:
        static_primary = None
    if tier_id == "free":
        static_fallback = FREE_FALLBACK_B14_MODEL_ID
    return await resolve_tier_route_view_from_stores(
        route_store, policy_store, product="claw", tier=_TIER_BY_ID[tier_id],
        static_primary=static_primary, static_fallback=static_fallback,
    )


async def resolve_claw_tier_model_from_stores(
    route_store: object, policy_store: object, tier_id: str,
) -> TierRouteResolution:
    resolution, _revision = await resolve_claw_tier_model_view_from_stores(
        route_store, policy_store, tier_id,
    )
    return resolution


async def resolve_claw_tier_model_view(
    request: Request, tier_id: str,
) -> tuple[TierRouteResolution, int]:
    return await resolve_claw_tier_model_view_from_stores(
        _store(request),
        getattr(request.app.state, "central_model_policy_store", None),
        tier_id,
    )


async def resolve_claw_tier_model(
    request: Request, tier_id: str,
) -> TierRouteResolution:
    resolution, _revision = await resolve_claw_tier_model_view(request, tier_id)
    return resolution


__all__ = [
    "CentralRouteUnavailable",
    "WORKSPACE",
    "chat_request_tier_context",
    "resolve_chat_tier_route",
    "resolve_claw_tier_model",
    "resolve_claw_tier_model_from_stores",
    "resolve_claw_tier_model_view",
    "resolve_claw_tier_model_view_from_stores",
    "resolve_tier_route",
    "resolve_tier_route_from_stores",
    "resolve_tier_route_view_from_stores",
]
