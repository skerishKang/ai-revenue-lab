"""Staged tier model groups and per-product primary/explicit backup plan.

S0 contract ONLY: no D1 writes, no B14/provider dispatch, no user entitlement
grant, no implicit fallback. B14 remains the canonical model/credential source.
A later separately-reviewed store/runtime integration must verify D1 policy,
the authenticated member tier, current catalog, product gates and audit.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .contracts import ControlPlaneContractError
from .model_assignment_policy import (
    TIERS, CatalogModel, ModelPolicySnapshot, MODEL_ID, effective_model,
)
from .product_tier_routes import (
    PLUS_HOLD_MODEL_ID, PRO_HOLD_MODEL_ID, MAX_HOLD_MODEL_ID,
    RETIRED_PRODUCT_MODEL_IDS,
)

SITE_PRODUCTS = frozenset({"chat", "claw", "b66"})
MAX_GROUP_MODELS = 32
MAX_BACKUPS = 2
NON_EXECUTABLE_IDS = RETIRED_PRODUCT_MODEL_IDS | frozenset({
    PLUS_HOLD_MODEL_ID, PRO_HOLD_MODEL_ID, MAX_HOLD_MODEL_ID,
})
# Only retryable provider/transport errors are eligible. Never retry policy,
# identity, approval, quotas, auth, safety refusals or invalid model profiles.
TRANSIENT_FAILOVER_CODES = frozenset({
    "upstream_timeout", "upstream_rate_limited", "upstream_unavailable",
    "upstream_server_error", "provider_server_error", "upstream_busy",
})


def _reject(code: str) -> None:
    raise ControlPlaneContractError(code, code)


def _model_id(value: str) -> str:
    if (not isinstance(value, str) or MODEL_ID.fullmatch(value) is None
            or value.startswith("b14/auto") or value in NON_EXECUTABLE_IDS):
        _reject("invalid_tier_group_model")
    return value


@dataclass(frozen=True, slots=True)
class TierModelGroup:
    """A centrally proposed roster, NOT the customer's subscription tier."""
    tier: str
    model_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.tier not in TIERS or not isinstance(self.model_ids, tuple):
            _reject("invalid_tier_group")
        if len(self.model_ids) > MAX_GROUP_MODELS:
            _reject("tier_group_too_large")
        for model_id in self.model_ids:
            _model_id(model_id)
        if len(set(self.model_ids)) != len(self.model_ids):
            _reject("duplicate_tier_group_model")


@dataclass(frozen=True, slots=True)
class ProductModelPreference:
    """Different sites can choose different priorities inside one tier group."""
    product: str
    tier: str
    primary_model_id: str
    fallback_model_ids: tuple[str, ...] = ()
    fallback_enabled: bool = False

    def __post_init__(self) -> None:
        if self.product not in SITE_PRODUCTS or self.tier not in TIERS:
            _reject("invalid_product_group_target")
        _model_id(self.primary_model_id)
        if not isinstance(self.fallback_model_ids, tuple) or len(self.fallback_model_ids) > MAX_BACKUPS:
            _reject("invalid_product_group_fallbacks")
        for model_id in self.fallback_model_ids:
            _model_id(model_id)
        ids = (self.primary_model_id, *self.fallback_model_ids)
        if len(set(ids)) != len(ids) or type(self.fallback_enabled) is not bool:
            _reject("invalid_product_group_fallbacks")


@dataclass(frozen=True, slots=True)
class StagedTierGroupSnapshot:
    workspace_id: str
    revision: int
    groups: tuple[TierModelGroup, ...]
    preferences: tuple[ProductModelPreference, ...]

    def __post_init__(self) -> None:
        # Revision is a proposed CAS version; this contract does not persist it.
        if (not isinstance(self.workspace_id, str) or not self.workspace_id
                or len(self.workspace_id) > 128 or type(self.revision) is not int
                or self.revision < 0 or not isinstance(self.groups, tuple)
                or not isinstance(self.preferences, tuple)):
            _reject("invalid_tier_group_snapshot")
        if any(not isinstance(group, TierModelGroup) for group in self.groups):
            _reject("invalid_tier_group_snapshot")
        if any(not isinstance(p, ProductModelPreference) for p in self.preferences):
            _reject("invalid_tier_group_snapshot")
        by_tier = {group.tier: group for group in self.groups}
        if len(by_tier) != len(self.groups):
            _reject("duplicate_tier_group")
        keys = {(p.product, p.tier) for p in self.preferences}
        if len(keys) != len(self.preferences):
            _reject("duplicate_product_group_route")
        for p in self.preferences:
            group = by_tier.get(p.tier)
            if group is None or not set((p.primary_model_id, *p.fallback_model_ids)) <= set(group.model_ids):
                _reject("product_route_outside_tier_group")


@dataclass(frozen=True, slots=True)
class ProductGroupPreview:
    product: str
    tier: str
    primary_model_id: str | None
    eligible_fallback_model_ids: tuple[str, ...]
    model_reasons: tuple[tuple[str, str], ...]
    fallback_enabled: bool
    # No authorization to dispatch or change any production route.
    persisted: bool = False
    runtime_enforced: bool = False
    dispatch_authorized: bool = False


def preview_product_group(
    staged: StagedTierGroupSnapshot, *, product: str, tier: str,
    workspace_id: str, policy: ModelPolicySnapshot | None,
    catalog: Mapping[str, CatalogModel],
    capability_ready: Mapping[str, bool],
    trusted_policy_fresh: bool,
) -> ProductGroupPreview:
    """Read-only intersection of staged group and actual central + site D1 grants.

    Trusted host must provide catalog, policy, entitlement/capability readiness.
    Missing or stale policy fails closed. Nothing here authorizes a call.
    """
    if not isinstance(staged, StagedTierGroupSnapshot) or staged.workspace_id != workspace_id:
        _reject("invalid_tier_group_workspace")
    if product not in SITE_PRODUCTS or tier not in TIERS:
        _reject("invalid_product_group_target")
    pref = next((p for p in staged.preferences if (p.product, p.tier) == (product, tier)), None)
    if pref is None:
        return ProductGroupPreview(product, tier, None, (), (), False)
    if not isinstance(catalog, Mapping) or not isinstance(capability_ready, Mapping):
        _reject("invalid_tier_group_catalog")
    rows: list[tuple[str, str]] = []
    ready: set[str] = set()
    for model_id in (pref.primary_model_id, *pref.fallback_model_ids):
        result = effective_model(
            policy, workspace_id=workspace_id, product=product, tier=tier,
            model=catalog.get(model_id), model_id=model_id,
            capability_ready=capability_ready.get(model_id) is True,
            trusted_policy_fresh=trusted_policy_fresh is True,
        )
        rows.append((model_id, result.reason))
        if result.allowed:
            ready.add(model_id)
    return ProductGroupPreview(
        product, tier,
        pref.primary_model_id if pref.primary_model_id in ready else None,
        tuple(mid for mid in pref.fallback_model_ids if mid in ready),
        tuple(rows), pref.fallback_enabled,
    )


def suggest_explicit_fallback(
    preview: ProductGroupPreview, *, failure_code: str,
    attempted_model_ids: tuple[str, ...], user_notice_possible: bool,
) -> str | None:
    """Return an ADVISORY next exact ID, not a dispatch/fallback side effect.

    Integration must still recheck the actual trusted policy and owner grant,
    emit a user-visible route-change notice, preserve full conversation context,
    and emit an audit event before executing. Never fall back on a policy error.
    """
    if (not isinstance(preview, ProductGroupPreview)
            or preview.primary_model_id is None
            or not preview.fallback_enabled
            or failure_code not in TRANSIENT_FAILOVER_CODES
            or user_notice_possible is not True
            or not isinstance(attempted_model_ids, tuple)
            or not attempted_model_ids
            or attempted_model_ids[0] != preview.primary_model_id
            or len(set(attempted_model_ids)) != len(attempted_model_ids)):
        return None
    eligible = (preview.primary_model_id, *preview.eligible_fallback_model_ids)
    if attempted_model_ids != eligible[:len(attempted_model_ids)]:
        return None
    return eligible[len(attempted_model_ids)] if len(attempted_model_ids) < len(eligible) else None
