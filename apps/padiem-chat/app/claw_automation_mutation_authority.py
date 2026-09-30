"""Shared OWNER mutation authority for Web Automation (#3262).

Web Automation gained its first mutation surface with #3257 (Create). Every
further mutation — enable/disable here, and Edit/Delete later — must answer the
*same* authorization question with the *same* code, so this module is the one
place that answers it:

```text
signed Padiem Chat session
  -> current active B54 canonical session      (#3243 resolver, reused)
  -> session tenant + canonical subject        (never caller supplied)
  -> exact ACTIVE role-bearing tenant membership
  -> role == OWNER
  -> AutomationOwnerMutationContext
```

Deliberately refused here:

* the Claw Memory owner fallback (``f"owner:{user_id}"``) — a synthetic
  per-owner workspace would be a second, non-canonical authority;
* any caller-supplied tenant, subject, role, product user or member id;
* a second membership grammar — the existing Control Plane predicate and the
  canonical ``TenantMembership`` contract are reused as-is;
* any browser identity output — the context is server-side only, and every
  route answers with the existing safe rule projection.

Callers supply only their action-specific denial copy; the chain, status codes
and failure modes are identical for Create and Toggle.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from padiem_control_plane.auth_sessions import AuthSessionSnapshot
from padiem_control_plane.tenants import TenantMembership, TenantMembershipRole, TenantMembershipState

from .claw_automation_rules_routes import _error, _require_owner

__all__ = [
    "AutomationOwnerMutationContext",
    "OWNER_MUTATION_DENIED_MESSAGE",
    "require_owner_membership",
    "resolve_automation_owner_mutation_context",
]

# Action-neutral default: routes pass their own copy so the browser message
# matches the action, while the authority chain stays single-sourced.
OWNER_MUTATION_DENIED_MESSAGE = "워크스페이스 소유자만 변경할 수 있습니다."


@dataclass(frozen=True, slots=True)
class AutomationOwnerMutationContext:
    """Server-side authorization result for one Automation mutation."""

    auth_session: AuthSessionSnapshot
    tenant_id: str
    canonical_subject_id: str
    membership: TenantMembership


def _server_utc() -> datetime:
    return datetime.now(timezone.utc)


def require_owner_membership(
    membership: Any, *, tenant_id: str, canonical_subject_id: str
) -> bool:
    """Exactly this tenant+subject, ACTIVE, and role == OWNER."""

    return (
        isinstance(membership, TenantMembership)
        and membership.tenant_id == tenant_id
        and membership.canonical_subject_id == canonical_subject_id
        and membership.state is TenantMembershipState.ACTIVE
        and membership.role is TenantMembershipRole.OWNER
    )


async def _current_b54_session(request: Request) -> Any | None:
    """The #3243 current B54 session for the signed-in user, or None."""

    from .b54_canonical_session import resolve_current_b54_canonical_session

    try:
        return await resolve_current_b54_canonical_session(request)
    except Exception:
        return None


async def resolve_automation_owner_mutation_context(
    request: Request, *, denied_message: str = OWNER_MUTATION_DENIED_MESSAGE
) -> tuple[AutomationOwnerMutationContext | None, JSONResponse | None]:
    """Resolve the OWNER mutation context, or return one bounded error response.

    Exactly one authority for Create (#3257) and Toggle (#3262):

    - signed out -> 401 ``unauthorized``;
    - no current active B54 session (including a foreign-product one) -> 403
      ``current_b54_session_unavailable`` without disclosure;
    - membership that is not exactly this tenant+subject, ACTIVE and OWNER ->
      403 ``owner_role_required`` (viewer/operator/approver, and no role or
      identity detail about the caller is disclosed);
    - the Control Plane membership authority being unavailable -> bounded 503.

    On success the tenant and canonical subject come only from the canonical
    session; the membership is the exact revalidated relation.
    """

    uid = _require_owner(request)
    if uid is None:
        return None, _error(401, "unauthorized", "인증이 필요합니다.")

    bridged = await _current_b54_session(request)
    if bridged is None:
        return None, _error(
            403,
            "current_b54_session_unavailable",
            "자동화를 변경할 수 없습니다. 세션을 확인해 주세요.",
        )
    auth_session = bridged.auth_session
    tenant_id = auth_session.tenant_id
    canonical_subject_id = auth_session.subject.subject_id
    if not isinstance(tenant_id, str) or not tenant_id or not canonical_subject_id:
        return None, _error(
            403,
            "current_b54_session_unavailable",
            "자동화를 변경할 수 없습니다. 세션을 확인해 주세요.",
        )

    authority = getattr(request.app.state, "control_plane_identity_authority", None)
    if authority is None or not callable(
        getattr(authority, "resolve_active_tenant_membership", None)
    ):
        return None, _error(
            503, "canonical_membership_unavailable", "워크스페이스 권한을 확인할 수 없습니다."
        )
    try:
        membership = await authority.resolve_active_tenant_membership(
            tenant_id=tenant_id,
            canonical_subject_id=canonical_subject_id,
            now=_server_utc(),
        )
    except Exception:
        return None, _error(403, "owner_role_required", denied_message)
    if not require_owner_membership(
        membership, tenant_id=tenant_id, canonical_subject_id=canonical_subject_id
    ):
        return None, _error(403, "owner_role_required", denied_message)

    return (
        AutomationOwnerMutationContext(
            auth_session=auth_session,
            tenant_id=tenant_id,
            canonical_subject_id=canonical_subject_id,
            membership=membership,
        ),
        None,
    )
