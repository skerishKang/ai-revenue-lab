"""PADIEM Custom (BYOK) credential management over the canonical product session.

Routes only expose credential metadata. The raw provider key is accepted once,
sealed server-side, and never returned to the browser or written to logs.
"""
from __future__ import annotations

import json

from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id
from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .byok_credentials import (
    CUSTOM_PROVIDERS,
    validate_custom_api_key,
)

MAX_CUSTOM_CREDENTIAL_BODY_BYTES = 4096
HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "X-Content-Type-Options": "nosniff",
}


def _error(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": {"code": code, "message": message}},
        status_code=status_code,
        headers=HEADERS,
    )


async def _owner(request: Request) -> str | None:
    uid = current_user_id(request) if auth_ready(request) else None
    store = getattr(request.app.state, "history_store", None)
    if not uid or store is None:
        return None
    try:
        return uid if await store.get_user(uid) is not None else None
    except Exception:
        return None


def _store(request: Request):
    return getattr(request.app.state, "custom_credential_store", None)


def _provider_options() -> list[dict[str, str]]:
    return [
        {
            "provider": spec.provider_id,
            "model": spec.model_id,
            "display_name": spec.display_name,
        }
        for spec in CUSTOM_PROVIDERS.values()
    ]


async def custom_credential_status(request: Request):
    uid = await _owner(request)
    if not uid:
        return _error("authentication_required", "로그인이 필요합니다.", 401)
    store = _store(request)
    if store is None:
        return _error(
            "custom_provider_unavailable",
            "PADIEM Custom을 현재 사용할 수 없습니다.",
            503,
        )
    try:
        credentials = await store.status(uid)
    except Exception:
        return _error(
            "custom_credential_unavailable",
            "PADIEM Custom 자격증명을 확인할 수 없습니다.",
            503,
        )
    return JSONResponse(
        {"ok": True, "credentials": credentials, "providers": _provider_options()},
        headers=HEADERS,
    )


async def custom_credential_save(request: Request):
    uid = await _owner(request)
    if not uid:
        return _error("authentication_required", "로그인이 필요합니다.", 401)
    store = _store(request)
    if store is None:
        return _error(
            "custom_provider_unavailable",
            "PADIEM Custom을 현재 사용할 수 없습니다.",
            503,
        )
    if request.query_params:
        return _error(
            "custom_credential_request_invalid",
            "요청 형식이 올바르지 않습니다.",
            400,
        )
    try:
        body = await read_bounded_request_body(
            request, max_bytes=MAX_CUSTOM_CREDENTIAL_BODY_BYTES
        )
        raw = json.loads(body.decode("utf-8"))
    except RequestBodyTooLarge:
        return _error(
            "request_too_large", "요청이 너무 큽니다.", 413
        )
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error(
            "custom_credential_request_invalid",
            "요청 형식이 올바르지 않습니다.",
            422,
        )
    if not isinstance(raw, dict) or set(raw) != {"provider", "api_key"}:
        return _error(
            "custom_credential_request_invalid",
            "요청 형식이 올바르지 않습니다.",
            422,
        )
    provider = raw.get("provider")
    if not isinstance(provider, str) or provider not in CUSTOM_PROVIDERS:
        return _error(
            "custom_provider_unsupported",
            "지원하지 않는 PADIEM Custom 공급사입니다.",
            422,
        )
    try:
        api_key = validate_custom_api_key(raw.get("api_key"))
    except ValueError as exc:
        return _error("custom_key_invalid", str(exc), 422)
    try:
        credential = await store.save(
            user_id=uid, provider_id=provider, api_key=api_key
        )
    except Exception:
        return _error(
            "custom_credential_save_failed",
            "PADIEM Custom 자격증명을 저장하지 못했습니다.",
            503,
        )
    return JSONResponse({"ok": True, "credential": credential}, headers=HEADERS)


async def custom_credential_delete(request: Request):
    uid = await _owner(request)
    if not uid:
        return _error("authentication_required", "로그인이 필요합니다.", 401)
    store = _store(request)
    if store is None:
        return _error(
            "custom_provider_unavailable",
            "PADIEM Custom을 현재 사용할 수 없습니다.",
            503,
        )
    if request.headers.get("content-length") not in (None, "", "0"):
        return _error(
            "custom_credential_request_invalid",
            "요청 형식이 올바르지 않습니다.",
            400,
        )
    if set(request.query_params.keys()) != {"provider"}:
        return _error(
            "custom_credential_request_invalid",
            "요청 형식이 올바르지 않습니다.",
            400,
        )
    provider = request.query_params.get("provider")
    if provider not in CUSTOM_PROVIDERS:
        return _error(
            "custom_provider_unsupported",
            "지원하지 않는 PADIEM Custom 공급사입니다.",
            422,
        )
    try:
        deleted = await store.delete(uid, provider)
    except Exception:
        return _error(
            "custom_credential_delete_failed",
            "PADIEM Custom 자격증명을 삭제하지 못했습니다.",
            503,
        )
    return JSONResponse(
        {"ok": True, "deleted": bool(deleted), "provider": provider},
        headers=HEADERS,
    )
