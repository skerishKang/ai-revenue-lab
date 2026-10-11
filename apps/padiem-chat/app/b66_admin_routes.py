"""Admin-only B66 membership HTTP surface; all authority comes from signed session + D1."""
from __future__ import annotations

import json
import re

from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import current_user_id
from .b66_member_admin import MemberConflict, MemberMissing
from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body

_NO_STORE = {"Cache-Control": "no-store, max-age=0"}
_USER_ID = re.compile(r"usr_[0-9a-f]{32}\Z")


def _error(status: int, code: str) -> JSONResponse:
    return JSONResponse({"ok": False, "error": {"code": code}}, status_code=status, headers=_NO_STORE)


async def _admin(request: Request) -> tuple[object | None, str | None, JSONResponse | None]:
    uid = current_user_id(request)
    if not uid:
        return None, None, _error(401, "auth_required")
    store = getattr(request.app.state, "b66_member_admin_store", None)
    if store is None:
        return None, None, _error(503, "admin_unavailable")
    try:
        if not await store.is_google_admin(uid):
            return None, None, _error(403, "admin_forbidden")
    except Exception:
        return None, None, _error(503, "admin_unavailable")
    return store, uid, None


async def b66_admin_me(request: Request) -> JSONResponse:
    uid = current_user_id(request)
    if not uid:
        return JSONResponse({"ok": True, "admin": False}, headers=_NO_STORE)
    store = getattr(request.app.state, "b66_member_admin_store", None)
    if store is None:
        return JSONResponse({"ok": True, "admin": False}, headers=_NO_STORE)
    try:
        allowed = await store.is_google_admin(uid)
    except Exception:
        allowed = False
    return JSONResponse({"ok": True, "admin": allowed is True}, headers=_NO_STORE)


async def b66_admin_members(request: Request) -> JSONResponse:
    store, _, err = await _admin(request)
    if err is not None:
        return err
    raw_limit = request.query_params.get("limit", "50")
    raw_offset = request.query_params.get("offset", "0")
    if not re.fullmatch(r"\d{1,3}", raw_limit) or not re.fullmatch(r"\d{1,5}", raw_offset):
        return _error(400, "invalid_pagination")
    limit, offset = int(raw_limit), int(raw_offset)
    if limit < 1 or limit > 100 or offset > 10000:
        return _error(400, "invalid_pagination")
    try:
        members = await store.list_members(limit=limit, offset=offset)
        counts = await store.count_members()
        notifications_pending = await store.undelivered_signups()
    except Exception:
        return _error(503, "membership_store_unavailable")
    return JSONResponse({"ok": True, "members": members, "counts": counts,
                         "signup_events_pending": notifications_pending,
                         "notification_delivery_configured": bool(getattr(getattr(request.app.state, "b66_signup_notifier", None), "channels", None))}, headers=_NO_STORE)


async def b66_admin_member_access(request: Request) -> JSONResponse:
    store, actor_id, err = await _admin(request)
    if err is not None:
        return err
    user_id = request.path_params.get("user_id")
    if not isinstance(user_id, str) or not _USER_ID.fullmatch(user_id):
        return _error(404, "member_not_found")
    if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
        return _error(415, "json_required")
    try:
        raw = await read_bounded_request_body(request, max_bytes=1024)
        data = json.loads(raw)
    except (RequestBodyTooLarge, ValueError, UnicodeDecodeError):
        return _error(400, "invalid_body")
    except Exception:
        return _error(400, "invalid_body")
    if not isinstance(data, dict) or set(data) != {"status", "tier", "expected_revision"}:
        return _error(400, "invalid_access_fields")
    if data.get("status") not in ("pending", "approved", "suspended"):
        return _error(400, "invalid_status")
    if data.get("tier") not in ("FREE", "PLUS", "PRO", "MAX"):
        return _error(400, "invalid_tier")
    if type(data.get("expected_revision")) is not int or data["expected_revision"] < 0:
        return _error(400, "invalid_revision")
    try:
        result = await store.set_access(
            actor_id=actor_id, user_id=user_id, status=data["status"],
            tier=data["tier"], expected_revision=data["expected_revision"]
        )
    except MemberMissing:
        return _error(404, "member_not_found")
    except MemberConflict:
        return _error(409, "membership_version_conflict")
    except Exception:
        return _error(503, "membership_store_unavailable")
    return JSONResponse({"ok": True, "access": result}, headers=_NO_STORE)


async def _registered_models(request: Request) -> list[dict] | None:
    resolver = getattr(request.app.state, "b66_quote_model_resolver", None)
    list_fn = getattr(resolver, "list_selectable_models", None)
    if not callable(list_fn):
        return None
    try:
        result = await list_fn()
    except Exception:
        return None
    if not isinstance(result, list):
        return None
    return [
        {"model_id": row["model_id"], "name": row["name"]}
        for row in result
        if isinstance(row, dict) and isinstance(row.get("model_id"), str)
        and isinstance(row.get("name"), str)
    ]


async def b66_admin_model_policy(request: Request) -> JSONResponse:
    store, actor_id, err = await _admin(request)
    if err is not None:
        return err
    # A model is assignable only when the trusted B14 resolver actually
    # declares it owner-allowlisted and credential/live-ready.
    models = await _registered_models(request)
    if models is None:
        return _error(503, "model_registry_unavailable")
    if request.method == "GET":
        try:
            current = await store.model_policy()
        except Exception:
            return _error(503, "membership_store_unavailable")
        return JSONResponse({"ok": True, "models": models, "policy": current,
                             "enforcement_enabled": getattr(request.app.state, "b66_membership_enforced", False) is True}, headers=_NO_STORE)

    if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
        return _error(415, "json_required")
    try:
        raw = await read_bounded_request_body(request, max_bytes=16384)
        data = json.loads(raw)
    except (RequestBodyTooLarge, ValueError, UnicodeDecodeError):
        return _error(400, "invalid_body")
    except Exception:
        return _error(400, "invalid_body")
    if not isinstance(data, dict) or set(data) != {
        "expected_revision", "active", "tiers"
    }:
        return _error(400, "invalid_policy_fields")
    if data["active"] is True and getattr(request.app.state, "b66_membership_enforced", False) is not True:
        return _error(409, "membership_rollout_not_enabled")
    try:
        updated = await store.set_model_policy(
            actor_id=actor_id, expected_revision=data["expected_revision"],
            active=data["active"], tiers=data["tiers"],
            registered_models={m["model_id"] for m in models},
        )
    except ValueError:
        return _error(400, "invalid_model_policy")
    except MemberConflict:
        return _error(409, "membership_version_conflict")
    except Exception:
        return _error(503, "membership_store_unavailable")
    return JSONResponse({"ok": True, "policy": updated}, headers=_NO_STORE)


async def b66_admin_dispatch_alerts(request: Request) -> JSONResponse:
    _, _, err = await _admin(request)
    if err is not None:
        return err
    notifier = getattr(request.app.state, "b66_signup_notifier", None)
    if notifier is None or not notifier.channels:
        return _error(503, "signup_notifications_not_configured")
    # A bounded admin-only retry; no URL/chat ID or email recipient is accepted
    # from the browser. The per-user/channel D1 receipt prevents replaying
    # deliveries already acknowledged as successful.
    try:
        result = await notifier.retry_pending(limit=5)
    except Exception:
        return _error(503, "signup_notification_retry_failed")
    return JSONResponse({"ok":True, "result":result}, headers=_NO_STORE)
