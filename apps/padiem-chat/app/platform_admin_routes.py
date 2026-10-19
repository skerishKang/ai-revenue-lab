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

import inspect
import json
import re

from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id
from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
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
        "capabilities": {
            "admin_hub": False,
            "role_management": False,
            "b66_customer_admin": False,
            "central_model_admin": False,
        },
    }


async def _verify(authority: object, attribute: str, user_id: str) -> bool:
    verify = getattr(authority, attribute, None)
    if not callable(verify):
        return False
    try:
        result = verify(user_id=user_id)
        result = await result if inspect.isawaitable(result) else result
    except Exception:
        return False
    return result is True


async def _legacy_super_admin(request: Request, user_id: str) -> bool:
    authority = getattr(request.app.state, "central_model_admin_authorizer", None)
    return await _verify(authority, "is_global_model_admin", user_id)


async def _b66_customer_admin(request: Request, user_id: str) -> bool:
    authority = getattr(request.app.state, "b66_member_admin_store", None)
    verify = getattr(authority, "is_google_admin", None)
    if not callable(verify):
        return False
    try:
        result = verify(user_id)
        result = await result if inspect.isawaitable(result) else result
    except Exception:
        return False
    return result is True


async def _stored_role(request: Request, user_id: str) -> str | None:
    store = getattr(request.app.state, "platform_admin_role_store", None)
    if store is None:
        raise RuntimeError("platform admin role store is not configured")
    return await store.role_for(user_id)


async def _resolve_role(request: Request, user_id: str) -> tuple[str | None, bool]:
    """Return the integrated role and the independent central authority result.

    The trusted central operator binding keeps its existing SUPER_ADMIN
    authority even before any role row exists. A stored role can add an ADMIN;
    it can never remove that pre-existing authority.
    """
    central = await _legacy_super_admin(request, user_id)
    stored = await _stored_role(request, user_id)
    if central:
        return ROLE_SUPER_ADMIN, True
    return stored, False


def _capabilities(role: str | None, *, b66: bool, central: bool) -> dict[str, bool]:
    return {
        "admin_hub": role is not None,
        "role_management": role == ROLE_SUPER_ADMIN,
        "b66_customer_admin": b66,
        "central_model_admin": central,
    }


async def platform_admin_session(request: Request) -> JSONResponse:
    if not auth_ready(request):
        return JSONResponse(_unauthenticated(), headers=_NO_STORE)
    user_id = current_user_id(request)
    if not user_id:
        return JSONResponse(_unauthenticated(), headers=_NO_STORE)
    try:
        role, central = await _resolve_role(request, user_id)
        b66 = await _b66_customer_admin(request, user_id)
    except Exception:
        return _error(503, "admin_role_store_unavailable")
    return JSONResponse(
        {
            "ok": True,
            "authenticated": True,
            "role": role,
            "capabilities": _capabilities(role, b66=b66, central=central),
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
        role, _ = await _resolve_role(request, user_id)
    except Exception:
        return None, _error(503, "admin_role_store_unavailable")
    if role != ROLE_SUPER_ADMIN:
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
    except AdminRoleActorMissing:
        return _error(403, "role_management_forbidden")
    except Exception:
        return _error(503, "admin_role_store_unavailable")
    return JSONResponse(
        {"ok": True, "revocation": revocation.public_dict()}, headers=_NO_STORE
    )
