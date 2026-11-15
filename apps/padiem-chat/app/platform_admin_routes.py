"""#5118 integrated administrator session and role-management API.

The signed product session is the only identity input. All authority is read
from the canonical users row plus the existing product authorizers; no email,
role, or admin flag from the browser is trusted.

Existing product authorities stay independent:
* a B66 customer administrator never becomes a global model administrator;
* ADMIN never receives B66 customer data or B14 model administration from the
  integrated role alone. The session response reports the actual product
  capabilities so the UI can gate what the APIs will really allow.
"""
from __future__ import annotations

import json
import re

from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id
from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .platform_admin_authority import platform_authority_for
from .platform_admin_roles import (
    ROLE_SUPER_ADMIN,
    ROLES,
    AdminRoleActorMissing,
    AdminRoleTargetMissing,
)

_NO_STORE = {
    "Cache-Control": "private, no-store, max-age=0",
    "Pragma": "no-cache",
    "X-Content-Type-Options": "nosniff",
}
_UID = re.compile(r"usr_[0-9a-f]{32}\Z")
_BODY_LIMIT = 1024


def _error(status: int, code: str) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": {"code": code}},
        status_code=status,
        headers=_NO_STORE,
    )


def _unauthenticated() -> dict:
    return {
        "ok": True,
        "authenticated": False,
        "role": None,
        "capabilities": _capabilities(
            None, b66_customer=False, b66_platform=False
        ),
    }


def _capabilities(
    role: str | None, *, b66_customer: bool, b66_platform: bool,
    site_feedback_admin: bool = False,
) -> dict[str, bool]:
    # Chat/Claw management is the existing shared B14 model-route surface.
    # B66 customer data is intentionally not derived from the platform role.
    # site_feedback_admin (#7690 stage 2) is a separate per-site designation,
    # never implied by any platform role.
    return {
        "admin_hub": role is not None,
        "role_management": role == ROLE_SUPER_ADMIN,
        "chat_admin": role is not None,
        "claw_admin": role is not None,
        "b66_platform_admin": b66_platform,
        "b66_customer_admin": b66_customer,
        "central_model_admin": role in ROLES,
        "site_feedback_admin": site_feedback_admin,
    }


async def platform_admin_session(request: Request) -> JSONResponse:
    if not auth_ready(request):
        return JSONResponse(_unauthenticated(), headers=_NO_STORE)
    user_id = current_user_id(request)
    if not user_id:
        return JSONResponse(_unauthenticated(), headers=_NO_STORE)
    authority = platform_authority_for(request)
    try:
        role = await authority.role_for(user_id)
        b66_customer = await authority.is_b66_customer_admin(user_id)
        b66_platform = await authority.is_b66_platform_admin(user_id)
    except Exception:
        return _error(503, "admin_role_store_unavailable")
    # #7690 stage 2: per-site feedback administration is an independent
    # designation read from the canonical D1, never derived from the role.
    site_feedback_sites: list[str] = []
    site_authority = getattr(request.app.state, "site_feedback_admin_authorizer", None)
    sites_for = getattr(site_authority, "sites_for", None) if site_authority is not None else None
    if callable(sites_for):
        try:
            found = await sites_for(user_id=user_id)
            site_feedback_sites = sorted(
                site for site in (found or ()) if isinstance(site, str) and site
            )
        except Exception:
            # A missing or unreadable site table only means "not a site admin".
            # It must never take the whole administrator hub session down.
            site_feedback_sites = []
    return JSONResponse(
        {
            "ok": True,
            "authenticated": True,
            "role": role,
            "site_feedback_sites": site_feedback_sites,
            "capabilities": _capabilities(
                role, b66_customer=b66_customer, b66_platform=b66_platform,
                site_feedback_admin=bool(site_feedback_sites),
            ),
        },
        headers=_NO_STORE,
    )


async def _require_super_admin(
    request: Request,
) -> tuple[str | None, JSONResponse | None]:
    if not auth_ready(request):
        return None, _error(401, "authentication_required")
    user_id = current_user_id(request)
    if not user_id:
        return None, _error(401, "authentication_required")
    try:
        allowed = await platform_authority_for(request).is_super_admin(user_id=user_id)
    except Exception:
        return None, _error(503, "admin_role_store_unavailable")
    if allowed is not True:
        return None, _error(403, "role_management_forbidden")
    return user_id, None


async def _json_body(request: Request) -> dict | None:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return None
    try:
        raw = await read_bounded_request_body(request, max_bytes=_BODY_LIMIT)
        data = json.loads(raw.decode("utf-8"))
    except (RequestBodyTooLarge, UnicodeDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


async def platform_admin_role_assign(request: Request) -> JSONResponse:
    actor, denied = await _require_super_admin(request)
    if denied is not None:
        return denied
    data = await _json_body(request)
    if data is None or set(data) != {"user_id", "role"}:
        return _error(400, "invalid_request")
    target, role = data.get("user_id"), data.get("role")
    if not isinstance(target, str) or _UID.fullmatch(target) is None:
        return _error(400, "invalid_user_id")
    if not isinstance(role, str) or role not in ROLES:
        return _error(400, "invalid_role")
    store = getattr(request.app.state, "platform_admin_role_store", None)
    try:
        assignment = await store.assign(
            actor_user_id=actor, target_user_id=target, role=role
        )
        from .auth_validation_cache import invalidate_auth_cache
        await invalidate_auth_cache(request, user_id=target)
    except AdminRoleTargetMissing:
        return _error(404, "canonical_user_not_found")
    except AdminRoleActorMissing:
        return _error(403, "role_management_forbidden")
    except Exception:
        return _error(503, "admin_role_store_unavailable")
    return JSONResponse(
        {"ok": True, "assignment": assignment.public_dict()}, headers=_NO_STORE
    )


async def platform_admin_role_revoke(request: Request) -> JSONResponse:
    actor, denied = await _require_super_admin(request)
    if denied is not None:
        return denied
    target = request.path_params.get("user_id")
    if not isinstance(target, str) or _UID.fullmatch(target) is None:
        return _error(400, "invalid_user_id")
    store = getattr(request.app.state, "platform_admin_role_store", None)
    try:
        revocation = await store.revoke(
            actor_user_id=actor, target_user_id=target
        )
        from .auth_validation_cache import invalidate_auth_cache
        await invalidate_auth_cache(request, user_id=target)
    except AdminRoleActorMissing:
        return _error(403, "role_management_forbidden")
    except Exception:
        return _error(503, "admin_role_store_unavailable")
    return JSONResponse(
        {"ok": True, "revocation": revocation.public_dict()}, headers=_NO_STORE
    )
