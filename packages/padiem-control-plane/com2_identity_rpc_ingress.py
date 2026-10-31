"""CPython identity RPC ingress; no identity authority or schema is created here.

Callers must supply the existing canonical identity authority bound to its
authoritative storage.  This adapter must not be deployed as a new authority.
"""
from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from internal_rpc_ingress import handle_internal_rpc

# The 9 existing identity ingress calls plus the three private enrollment
# methods needed by the connector pairing flow. This is a CPython-only set.
COM2_IDENTITY_RPC_METHODS = frozenset({
    "resolve_or_create_product_link", "establish_auth_session",
    "resolve_auth_session", "resolve_current_auth_session",
    "revoke_auth_session", "revoke_all_auth_sessions",
    "resolve_product_user_for_subject", "resolve_connector_workspace",
    "resolve_connector_context",
    "resolve_connector_enrollment_consent_for_device",
    "bind_connector_enrollment_challenge",
    "authorize_connector_enrollment_redeem",
    "issue_google_connect_ticket", "create_tenant", "get_tenant",
    "assign_tenant_membership", "revoke_tenant_membership",
    "resolve_active_memberships", "resolve_active_tenant_membership",
    "install_connector_enrollment_schema", "resolve_connector_owner_scope",
    "grant_connector_enrollment_consent", "revoke_connector_enrollment_consent",
})


def create_app(*, authority, secret: str) -> Starlette:
    """Construct the private ingress over an already configured authority.

    This is an injected composition seam, not a standalone production service;
    startup, loopback binding and state ownership must be wired separately.
    """
    if authority is None:
        raise ValueError("canonical identity authority required")
    if not isinstance(secret, str) or len(secret.strip()) < 32:
        raise ValueError("identity ingress secret is required")

    async def rpc(request: Request) -> JSONResponse:
        result = await handle_internal_rpc(
            request, secret=secret, allowed_methods=COM2_IDENTITY_RPC_METHODS,
            dispatcher=authority,
        )
        if result is None:
            return JSONResponse({"ok": False, "error": {"code": "not_found", "message": "Not Found"}}, status_code=404)
        status, payload, headers = result
        return JSONResponse(payload, status_code=status, headers=headers)

    return Starlette(routes=[Route("/internal/rpc/{method}", rpc, methods=["POST"])])
