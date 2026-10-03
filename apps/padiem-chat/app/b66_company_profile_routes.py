"""Authenticated B66 CompanyProfile routes (#3406)."""

from __future__ import annotations

import inspect
import json
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id
from .b66_company_profile import CompanyProfileError, PROFILE_KEYS, canonicalize_company_profile
from .claw_memory_routes import _resolve_memory_workspace

MAX_BODY_BYTES = 16 * 1024
_FORBIDDEN_OWNER_KEYS = frozenset({
    "user_id", "userId", "tenant_id", "tenantId", "workspace_id", "workspaceId", "owner"
})
_NO_STORE = {"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"}


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": {"code": code, "message": message}},
        status_code=status,
        headers=_NO_STORE,
    )
def _owner(request: Request) -> str | None:
    if not auth_ready(request):
        return None
    try:
        return current_user_id(request)
    except Exception:
        return None


def _store(request: Request) -> Any | None:
    return getattr(request.app.state, "b66_company_profile_store", None)


async def _json(request: Request) -> dict[str, Any] | JSONResponse:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return _error(415, "unsupported_media_type", "JSON 요청만 지원합니다.")
    body = await request.body()
    if not body:
        return _error(400, "empty_request_body", "요청 본문이 비어 있습니다.")
    if len(body) > MAX_BODY_BYTES:
        return _error(413, "request_too_large", "요청 크기가 너무 큽니다.")
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error(400, "invalid_json", "유효한 JSON 형식이 아닙니다.")
    if not isinstance(data, dict):
        return _error(400, "invalid_payload", "요청 데이터는 객체여야 합니다.")
    if any(key in data for key in _FORBIDDEN_OWNER_KEYS):
        return _error(400, "forbidden_owner_field", "계정 범위는 서버가 결정합니다.")
    if set(data) - PROFILE_KEYS:
        return _error(400, "unsupported_field", "지원되지 않는 회사정보 필드가 있습니다.")
    return data


async def b66_company_profile_get(request: Request) -> JSONResponse:
    uid = _owner(request)
    if uid is None:
        return _error(401, "unauthorized", "로그인이 필요합니다.")
    store = _store(request)
    get_fn = getattr(store, "get_profile", None) if store is not None else None
    if not callable(get_fn):
        return _error(503, "company_profile_unavailable", "회사정보 저장소를 사용할 수 없습니다.")
    workspace_id = await _resolve_memory_workspace(request, uid)
    try:
        value = get_fn(user_id=uid, workspace_id=workspace_id)
        profile = await value if inspect.isawaitable(value) else value
    except Exception:
        return _error(503, "company_profile_read_failed", "회사정보를 불러오지 못했습니다.")
    return JSONResponse(
        {"ok": True, "state": "ready" if profile else "missing", "company_profile": profile},
        headers=_NO_STORE,
    )
async def b66_company_profile_put(request: Request) -> JSONResponse:
    uid = _owner(request)
    if uid is None:
        return _error(401, "unauthorized", "로그인이 필요합니다.")
    data = await _json(request)
    if isinstance(data, JSONResponse):
        return data
    try:
        canonical = canonicalize_company_profile(data)
    except CompanyProfileError:
        return _error(400, "invalid_company_profile", "회사정보 값을 확인해 주세요.")

    store = _store(request)
    put_fn = getattr(store, "put_profile", None) if store is not None else None
    if not callable(put_fn):
        return _error(503, "company_profile_unavailable", "회사정보 저장소를 사용할 수 없습니다.")
    workspace_id = await _resolve_memory_workspace(request, uid)
    try:
        value = put_fn(user_id=uid, workspace_id=workspace_id, profile=canonical)
        profile = await value if inspect.isawaitable(value) else value
    except CompanyProfileError:
        return _error(400, "invalid_company_profile", "회사정보 값을 확인해 주세요.")
    except Exception:
        return _error(503, "company_profile_write_failed", "회사정보를 저장하지 못했습니다.")

    return JSONResponse({"ok": True, "state": "ready", "company_profile": profile}, headers=_NO_STORE)


__all__ = ["b66_company_profile_get", "b66_company_profile_put"]
