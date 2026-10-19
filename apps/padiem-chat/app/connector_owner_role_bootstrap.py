"""First-owner role bootstrap for shared PC enrollment (#4139).

The canonical tenant row of the very first owner predates roles
(`role IS NULL` by reviewed design: no default, no backfill). Enrollment
requires an explicit OWNER, and no existing route can set one. This module
adds the smallest possible execution wiring inside the existing owner
enrollment composition: one explicit, owner-self, roleless-to-OWNER action.

Hard boundaries (must stay true):

* SELF ONLY. Tenant and subject come exclusively from the verified canonical
  B54 session. No request field can name another subject, tenant, role, or
  product. Only the literal "owner" role is ever sent.
* ROLELESS ONLY. A membership that already carries any role is refused and
  never touched: no upgrade, no downgrade, no reactivation decision here.
  A second call is a harmless refusal, never a second write.
* EXACTLY ONE MEMBERSHIP. Zero memberships (normal tenant provisioning owns
  that) or more than one (ambiguous) both refuse before any write.
* NO NEW AUTHORITY. Uses only the existing private Identity Service Binding
  RPCs (`resolve_active_memberships`, `assign_tenant_membership`). No new
  server, table, worker, account, or auth system is created.
"""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse

from padiem_control_plane.tenants import TenantMembershipRole, TenantMembershipState

from .claw_connector_enrollment_routes import (
    _consent_payload,
    _error,
    _json,
    _verified_owner_request,
)
from .control_plane_identity import IdentityBridgeError

OWNER_ROLE_BOOTSTRAP_PATH = "/api/claw/connector/enrollments/bootstrap-owner-role"
_OWNER_ROLE_LITERAL = TenantMembershipRole.OWNER.value
_REFUSAL_STATUSES = {
    "connector_owner_bootstrap_consent_required": 400,
    "connector_owner_bootstrap_no_membership": 403,
    "connector_owner_bootstrap_ambiguous": 409,
    "connector_owner_bootstrap_role_present": 409,
}


async def bootstrap_owner_role(request: Request) -> JSONResponse:
    """Promote the caller's own roleless membership to OWNER, once."""
    session, denial = await _verified_owner_request(request)
    if denial is not None:
        return denial

    authority = getattr(request.app.state, "control_plane_identity_authority", None)
    if not callable(getattr(authority, "resolve_active_memberships", None)) or not callable(
        getattr(authority, "assign_tenant_membership", None)
    ):
        return _error(503, "enrollment_server_dependency_unavailable")

    wire = await _consent_payload(request, frozenset({"confirmed", "confirmation_version"}))
    if (
        wire is None
        or wire.get("confirmed") is not True
        or wire.get("confirmation_version") != "pc-enrollment-consent-v1"
    ):
        return _error(400, "connector_owner_bootstrap_consent_required")

    subject_id = session.subject.subject_id
    tenant_id = session.tenant_id
    try:
        memberships = await authority.resolve_active_memberships(
            canonical_subject_id=subject_id,
        )
        if tuple(memberships) != (tenant_id,):
            if len(tuple(memberships)) == 0:
                return _error(403, "connector_owner_bootstrap_no_membership")
            return _error(409, "connector_owner_bootstrap_ambiguous")
        current = await authority.assign_tenant_membership(
            tenant_id=tenant_id, canonical_subject_id=subject_id,
        )
        if current.role is not None:
            return _error(409, "connector_owner_bootstrap_role_present")
        updated = await authority.assign_tenant_membership(
            tenant_id=tenant_id, canonical_subject_id=subject_id, role=_OWNER_ROLE_LITERAL,
        )
        if (
            updated.role is not TenantMembershipRole.OWNER
            or updated.state is not TenantMembershipState.ACTIVE
        ):
            return _error(503, "enrollment_server_dependency_unavailable")
    except IdentityBridgeError as exc:
        status = exc.status_code if exc.status_code in (400, 401, 403, 404, 409, 429, 503) else 503
        code = exc.code if isinstance(exc.code, str) and exc.code else "enrollment_server_dependency_unavailable"
        if code in _REFUSAL_STATUSES:
            return _error(_REFUSAL_STATUSES[code], code)
        return _error(status, code)
    except Exception:
        return _error(503, "enrollment_server_dependency_unavailable")
    return _json({"ok": True, "bootstrapped": True}, 200)
