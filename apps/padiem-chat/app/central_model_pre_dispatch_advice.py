"""#4453 S3 readiness: host-only model policy decision, not a dispatch authorization.

The product host must authenticate the session, resolve a trusted product and tier,
verify capability/P01, and re-check at its final B14 dispatch boundary. This
adapter never calls a model or guesses a fallback and is NOT composed in a
production consumer by merely importing this module.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from padiem_control_plane.model_assignment_policy import (
    CatalogModel, ModelAvailability, ModelPolicySnapshot, PRODUCTS, TIERS,
    MODEL_ID, effective_model,
)

GLOBAL_WORKSPACE = "padiem-global"
_CANONICAL_USER = re.compile(r"usr_[a-f0-9]{32}\Z")


@dataclass(frozen=True)
class VerifiedProductModelSelection:
    """Created only by a canonical server-side product entitlement resolver."""
    canonical_user_id: str
    workspace_id: str
    product_id: str
    tier: str
    exact_model_id: str
    authority_ref: str

    def __post_init__(self):
        if not isinstance(self.canonical_user_id, str) or not _CANONICAL_USER.fullmatch(self.canonical_user_id):
            raise ValueError("missing_verified_model_user")
        if self.workspace_id != GLOBAL_WORKSPACE:
            raise ValueError("model_policy_workspace_not_supported")
        if self.product_id not in PRODUCTS - {"central"} or self.tier not in TIERS:
            raise ValueError("invalid_verified_model_target")
        if not isinstance(self.exact_model_id, str) or MODEL_ID.fullmatch(self.exact_model_id) is None or self.exact_model_id.startswith("b14/auto"):
            raise ValueError("invalid_verified_model_id")
        if not isinstance(self.authority_ref, str) or not self.authority_ref or len(self.authority_ref) > 128:
            raise ValueError("missing_verified_model_authority")


@dataclass(frozen=True)
class PreDispatchPolicyDecision:
    allowed: bool
    reason: str
    revision: int | None
    global_action: str
    product_action: str
    model_id: str
    product_id: str
    tier: str
    advisory_only: bool = True

    # This is an advisory state, NEVER a provider transport grant.
    @property
    def dispatch_authorized(self) -> bool:
        return False


def _denied(ctx: VerifiedProductModelSelection, reason: str) -> PreDispatchPolicyDecision:
    return PreDispatchPolicyDecision(
        False, reason, None, "unknown", "unknown",
        ctx.exact_model_id, ctx.product_id, ctx.tier,
    )


async def inspect_pre_dispatch_policy(
    *, selection: VerifiedProductModelSelection,
    store: Any, b14_catalog_source: Any,
    product_capability_verified: bool = False,
) -> PreDispatchPolicyDecision:
    """Fail-closed *advice* for a product handler; never dispatch on this result.

    The eventual product handler must gate final execution again against current
    D1 policy revision, B14 registry and real user/product/tier/P01 authority.
    """
    if not isinstance(selection, VerifiedProductModelSelection):
        raise ValueError("missing_verified_product_context")
    if type(product_capability_verified) is not bool or not product_capability_verified:
        return _denied(selection, "product_capability_unverified")
    get_snapshot = getattr(store, "snapshot", None)
    registered = getattr(b14_catalog_source, "list_registered_models", None)
    selectable = getattr(b14_catalog_source, "list_selectable_models", None)
    if not all(callable(f) for f in (get_snapshot, registered, selectable)):
        return _denied(selection, "model_policy_source_unavailable")
    try:
        snapshot = await get_snapshot(selection.workspace_id)
        reg_rows = await registered()
        eligible_rows = await selectable()
        if not isinstance(snapshot, ModelPolicySnapshot) or snapshot.workspace_id != selection.workspace_id:
            return _denied(selection, "model_policy_source_invalid")
        if not isinstance(reg_rows, list) or not isinstance(eligible_rows, list) or len(reg_rows) > 256 or len(eligible_rows) > 256:
            return _denied(selection, "b14_catalog_unavailable")
        found: dict[str, dict] = {}
        for row in reg_rows:
            if not isinstance(row, dict):
                return _denied(selection, "b14_catalog_invalid")
            mid = row.get("model_id")
            if not isinstance(mid, str) or MODEL_ID.fullmatch(mid) is None or mid in found or type(row.get("b14_enabled")) is not bool or type(row.get("owner_excluded")) is not bool:
                return _denied(selection, "b14_catalog_invalid")
            cap = row.get("capabilities")
            if not isinstance(cap, list) or any(not isinstance(c, str) for c in cap):
                return _denied(selection, "b14_catalog_invalid")
            found[mid] = row
        eligible_ids: set[str] = set()
        for row in eligible_rows:
            if not isinstance(row, dict) or not isinstance(row.get("model_id"), str):
                return _denied(selection, "b14_catalog_invalid")
            mid = row["model_id"]
            if mid in eligible_ids or mid not in found or not found[mid]["b14_enabled"] or found[mid]["owner_excluded"]:
                return _denied(selection, "b14_catalog_mismatch")
            eligible_ids.add(mid)
        exact = found.get(selection.exact_model_id)
        catalog_model = CatalogModel(
            model_id=selection.exact_model_id,
            registered=True,
            enabled=exact["b14_enabled"],
            credential_ready=selection.exact_model_id in eligible_ids,
            owner_allowed=not exact["owner_excluded"],
            capabilities=frozenset(exact["capabilities"]),
        ) if exact is not None else None
        evaluation: ModelAvailability = effective_model(
            snapshot, workspace_id=selection.workspace_id, product=selection.product_id,
            tier=selection.tier, model=catalog_model, model_id=selection.exact_model_id,
            capability_ready=True, trusted_policy_fresh=True,
        )
        return PreDispatchPolicyDecision(
            evaluation.allowed, evaluation.reason, evaluation.revision,
            evaluation.global_action, evaluation.product_action,
            selection.exact_model_id, selection.product_id, selection.tier,
        )
    except Exception:
        return _denied(selection, "model_policy_evaluation_unavailable")
