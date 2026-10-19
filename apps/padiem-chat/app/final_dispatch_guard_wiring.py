"""#4483: per-request final dispatch guard wiring for Chat/Claw.

Builds a :class:`~app.central_model_final_dispatch_guard.FinalDispatchGuard`
from the authenticated request context so the existing
``B14Client.with_guard()`` can wrap the transport for a single dispatch.

The guard is constructed per-request and never stored on the shared
``B14Client`` instance, so one user's authority can never leak into another
user's session.
"""

from __future__ import annotations

import re
from typing import Any

from padiem_control_plane.model_assignment_policy import ModelPolicySnapshot

from .auth_routes import current_user_id
from .b14_client import B14Client
from .central_model_final_dispatch_guard import (
    DispatchSessionContext,
    FinalDispatchGuard,
)
from .central_model_pre_dispatch_advice import (
    GLOBAL_WORKSPACE,
    VerifiedProductModelSelection,
)
from .member_grade_access import verified_member_grade
from .model_policy import current_request_tier_id

_CANONICAL_USER = re.compile(r"usr_[a-f0-9]{32}\Z")

# Guard tiers are the product tier labels from the control-plane contract
# (``TIERS``), not the lowercase routing profiles used by model_policy.
_REQUEST_TIER_TO_PRODUCT_TIER = {
    "free": "FREE",
    "plus": "PLUS",
    "pro": "PRO",
    "max": "MAX",
}
_GRADE_RANK = {"free": 0, "plus": 1, "pro": 2, "max": 3}

# Product ids handled by this guard.  Chat and B66 dispatch through separate
# client methods, so each route names its own product scope.
CHAT_PRODUCT_ID = "chat"
B66_PRODUCT_ID = "b66"


def _product_is_configured(snapshot: ModelPolicySnapshot, product_id: str) -> bool:
    """Whether the ledger contains any explicit rule for ``product_id``.

    #4483 stages enforcement per product: arming the guard against a ledger
    with zero product grants would deny every current customer instead of
    enforcing an owner decision.  An explicit product rule is the opt-in
    boundary; once present the guard stays fail-closed for unassigned models.
    """
    return any(rule.product == product_id for rule in snapshot.rules)


class SimpleB14CatalogSource:
    """Minimal B14 registry source backed by an async ``get_json`` callable.

    Used by the guard to verify that the requested model is registered and
    enabled in B14's catalog.  The transport callable is injected so the same
    source can be reused across requests and easily mocked in tests.
    """

    def __init__(self, get_json):
        self._get_json = get_json

    async def list_registered_models(self) -> list[dict]:
        status, body = await self._get_json("/api/pilot/models")
        if status != 200 or not isinstance(body, list):
            return []
        return body

    async def list_selectable_models(self) -> list[dict]:
        status, body = await self._get_json("/api/pilot/models")
        if status != 200 or not isinstance(body, list):
            return []
        return body


def _user_id_from_request(request) -> str | None:
    """Best-effort canonical user id from the signed session cookie.

    Returns None when the session is absent or the id is not in the canonical
    ``usr_<32-hex>`` form required by ``DispatchSessionContext``.
    """
    uid = current_user_id(request)
    if uid is None or _CANONICAL_USER.fullmatch(uid) is None:
        return None
    return uid


async def _guard_tier_label(request, user_id: str) -> str | None:
    """Resolve the product tier the guard must authorize for this dispatch.

    The route enters ``request_tier_context`` before resolving the model, so a
    mapped request tier is the tier whose route selected ``model_id``.  The
    admin-only tier is not a product tier in ``TIERS``; it falls back to the
    verified member grade, which is also what an unmapped legacy request uses.
    """
    tier_id = current_request_tier_id()
    mapped = _REQUEST_TIER_TO_PRODUCT_TIER.get(tier_id)
    if mapped is not None:
        return mapped
    grade = await verified_member_grade(request, user_id)
    if isinstance(grade, str) and grade.lower() in _GRADE_RANK:
        return grade.upper()
    return None


async def create_guard_from_request(
    request,
    model_id: str,
    store: Any,
    b14_catalog_source: Any,
    *,
    product_id: str = CHAT_PRODUCT_ID,
    requested_tier: str | None = None,
) -> FinalDispatchGuard | None:
    """Build a per-request :class:`FinalDispatchGuard` or ``None`` if the
    request context cannot be verified.

    Returns ``None`` when the session identity cannot be established in the
    canonical form required by ``DispatchSessionContext``, when the policy
    store / B14 catalog is not provisioned, or when the ledger has no explicit
    rule for this product yet (staged rollout is still OFF); callers then fall
    back to the unguarded client (existing behaviour preserved).

    ``requested_tier`` is for routes that validate a browser-selected lower
    grade against the verified membership themselves (B66): the guard then
    authorizes that grade and the live session must still entitle it.  Routes
    without an explicit selection (Chat) leave it ``None`` and keep deriving
    the tier from the request context or the verified member grade.
    """
    if store is None or b14_catalog_source is None:
        return None

    user_id = _user_id_from_request(request)
    if user_id is None:
        return None

    if requested_tier is not None:
        selected_tier_id = requested_tier.lower()
        if selected_tier_id not in _REQUEST_TIER_TO_PRODUCT_TIER:
            return None
        tier_label = _REQUEST_TIER_TO_PRODUCT_TIER[selected_tier_id]
        entitlement_tier_id = selected_tier_id
    else:
        tier_label = await _guard_tier_label(request, user_id)
        if tier_label is None:
            return None
        ambient_tier_id = current_request_tier_id()
        entitlement_tier_id = (
            ambient_tier_id
            if ambient_tier_id in _REQUEST_TIER_TO_PRODUCT_TIER
            else None
        )

    try:
        selection = VerifiedProductModelSelection(
            canonical_user_id=user_id,
            workspace_id=GLOBAL_WORKSPACE,
            product_id=product_id,
            tier=tier_label,
            exact_model_id=model_id,
            authority_ref=f"{product_id}:{user_id}:{model_id}",
        )
    except ValueError:
        return None

    # Read the current policy revision from the store so the guard can detect
    # drift between the revision captured at guard-creation time and the
    # revision in effect at dispatch time.
    try:
        snapshot = await store.snapshot(GLOBAL_WORKSPACE)
        if not isinstance(snapshot, ModelPolicySnapshot):
            return None
        if not _product_is_configured(snapshot, product_id):
            return None
        authorized_revision = snapshot.revision
    except Exception:
        return None

    async def session_reader() -> DispatchSessionContext | None:
        uid = current_user_id(request)
        if uid is None or _CANONICAL_USER.fullmatch(uid) is None:
            return None
        if entitlement_tier_id is not None:
            # Re-check that the live membership still entitles this dispatch
            # to the tier whose route selected the model. A downgrade denies.
            fresh_grade = await verified_member_grade(request, uid)
            if not isinstance(fresh_grade, str):
                return None
            fresh_grade = fresh_grade.lower()
            if _GRADE_RANK.get(fresh_grade, -1) < _GRADE_RANK[entitlement_tier_id]:
                return None
            member_tier = tier_label
        else:
            fresh_grade = await verified_member_grade(request, uid)
            if not isinstance(fresh_grade, str):
                return None
            member_tier = fresh_grade.upper()
            if member_tier != tier_label:
                return None
        return DispatchSessionContext(
            canonical_user_id=uid,
            workspace_id=GLOBAL_WORKSPACE,
            product_id=product_id,
            member_tier=member_tier,
            product_capability_verified=True,
        )

    return FinalDispatchGuard(
        selection=selection,
        current_session_reader=session_reader,
        store=store,
        b14_catalog_source=b14_catalog_source,
        authorized_revision=authorized_revision,
    )


def apply_guard_to_client(client: B14Client, guard: FinalDispatchGuard | None) -> B14Client:
    """Wrap ``client`` with ``guard`` when available, otherwise return it
    unchanged.  Safe to call with ``None``.
    """
    if guard is None:
        return client
    return client.with_guard(guard)
