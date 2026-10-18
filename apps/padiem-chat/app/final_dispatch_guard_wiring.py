"""#4483: per-request final dispatch guard wiring for Chat/Claw.

Builds a :class:`~app.central_model_final_dispatch_guard.FinalDispatchGuard`
from the authenticated request context so the existing
``B14Client.with_guard()`` can wrap the transport for a single dispatch.

The guard is constructed per-request and never stored on the shared
``B14Client`` instance, so one user's authority can never leak into another
user's session.
"""

from __future__ import annotations

import httpx
import re
from typing import Any

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
from .model_policy import TIER_ID_TO_PROFILE, _REQUEST_TIER_ID
from padiem_control_plane.model_assignment_policy import ModelPolicySnapshot

_CANONICAL_USER = re.compile(r"usr_[a-f0-9]{32}\Z")

# Product id handled by this guard (Chat/Claw share the same product scope).
CHAT_PRODUCT_ID = "chat"


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


def _tier_label_from_request(request) -> str:
    """Resolve the request tier label from the request context.

    ``request_tier_context`` is entered by the route handler before calling
    ``resolve_request_model_policy``.  We read the context var directly here so
    the guard can be built without re-running policy resolution.
    """
    tier_id = _REQUEST_TIER_ID.get()
    if tier_id is None:
        return "free"
    return TIER_ID_TO_PROFILE.get(tier_id, "free")


async def create_guard_from_request(
    request,
    model_id: str,
    store: Any,
    b14_catalog_source: Any,
) -> FinalDispatchGuard | None:
    """Build a per-request :class:`FinalDispatchGuard` or ``None`` if the
    request context cannot be verified.

    Returns ``None`` when the session identity cannot be established in the
    canonical form required by ``DispatchSessionContext``; callers should then
    fall back to the unguarded client (existing behaviour preserved).
    """
    user_id = _user_id_from_request(request)
    if user_id is None:
        return None

    tier_label = _tier_label_from_request(request)

    try:
        selection = VerifiedProductModelSelection(
            canonical_user_id=user_id,
            workspace_id=GLOBAL_WORKSPACE,
            product_id=CHAT_PRODUCT_ID,
            tier=tier_label,
            exact_model_id=model_id,
            authority_ref=f"chat:{user_id}:{model_id}",
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
        authorized_revision = snapshot.revision
    except Exception:
        return None

    async def session_reader() -> DispatchSessionContext | None:
        uid = current_user_id(request)
        if uid is None or _CANONICAL_USER.fullmatch(uid) is None:
            return None
        return DispatchSessionContext(
            canonical_user_id=uid,
            workspace_id=GLOBAL_WORKSPACE,
            product_id=CHAT_PRODUCT_ID,
            member_tier=tier_label,
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
