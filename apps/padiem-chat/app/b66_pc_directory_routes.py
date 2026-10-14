"""#4139/#4428: B66-specific, default-OFF, owner-scoped PC directory adapter.

This is a read-only product gate over the existing Claw/Web canonical Broker
projection. It must never create an identity/device/ONLINE authority or allow
P01/local execution. The source is composed exclusively by the trusted Worker,
and the default ProductPcAccessPolicy contains no grants.
"""
from __future__ import annotations

from typing import Any

from padiem_control_plane.local_agent_pc_access import (
    PcAccessOperation,
    ProductPcAccessPolicy,
    evaluate_pc_access,
)
from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id
from .claw_device_directory_routes import claw_device_directory
from .claw_memory_routes import _resolve_memory_workspace

B66_PC_DIRECTORY_PATH = "/api/b66/connect/devices"
_B66_PRODUCT_ID = "b66"
_NO_STORE = {
    "Cache-Control": "private, no-store, max-age=0",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


def _unavailable(reason: str) -> JSONResponse:
    return JSONResponse(
        {"ok": True, "available": False, "reason": reason},
        headers=_NO_STORE,
    )


async def b66_pc_directory_permission(request: Request, owner: str) -> bool:
    """Trusted product grant + authenticated workspace; never browser input.

    The public B66 listing intentionally requires an exact workspace-bound
    product grant. A global/unscoped configuration grant is insufficient for
    this customer-facing endpoint. No account emails, tier text, query
    parameters or client-selected product IDs are accepted as grants.
    """
    policy: Any = getattr(request.app.state, "b66_pc_access_policy", None)
    if not isinstance(policy, ProductPcAccessPolicy):
        return False
    grant = policy.grant_for(_B66_PRODUCT_ID)
    if grant is None or grant.workspace_ref is None:
        return False

    try:
        workspace = await _resolve_memory_workspace(request, owner)
    except Exception:
        return False
    if not workspace or grant.workspace_ref != workspace:
        return False

    decision = evaluate_pc_access(
        policy=policy, product_id=_B66_PRODUCT_ID,
        operation=PcAccessOperation.DEVICE_LIST,
        bound_product_id=_B66_PRODUCT_ID,
        workspace_ref=workspace,
    )
    if not decision.allowed:
        return False

    # The B66 product membership gate is independent of the PC grant.
    # When membership enforcement is enabled, missing/denied membership
    # must not be bypassed by a separate device.list grant.
    if getattr(request.app.state, "b66_membership_enforced", False) is True:
        store = getattr(request.app.state, "b66_member_admin_store", None)
        try:
            access = await store.runtime_access(owner)
        except Exception:
            return False
        if not isinstance(access, dict) or access.get("status") != "approved":
            return False
    return True


async def b66_pc_directory_available(request: Request, owner: str) -> bool:
    """Read-only UI hint; server route independently repeats the same guard."""
    source = getattr(request.app.state, "claw_device_directory_source", None)
    if getattr(source, "configured", False) is not True:
        return False
    return await b66_pc_directory_permission(request, owner)


async def b66_pc_directory(request: Request) -> JSONResponse:
    """B66 owner-only GET; reuse canonical Claw second serialization boundary."""
    if request.query_params:
        return JSONResponse(
            {"ok": False, "error": {"code": "b66_pc_query_not_allowed"}},
            status_code=400, headers=_NO_STORE,
        )
    owner = current_user_id(request) if auth_ready(request) else None
    if not owner:
        return JSONResponse(
            {"ok": False, "error": {"code": "unauthorized"}},
            status_code=401, headers=_NO_STORE,
        )
    if not await b66_pc_directory_available(request, owner):
        return _unavailable("b66_pc_not_enabled")

    # The existing Claw handler re-derives the owner/workspace and independently
    # validates the source's canonical Broker ONLINE/session data. Reuse exactly
    # that closed, secret-free and READ-ONLY JSON projection; no new authority.
    return await claw_device_directory(request)


B66_PC_MUTATION = False
B66_PC_DISPATCH_AUTHORIZED = False
B66_PC_PRODUCTION_DEFAULT = "off"
B66_PC_SECOND_DEVICE_AUTHORITY = False
