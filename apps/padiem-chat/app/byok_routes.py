"""PADIEM Custom (BYOK) credential management over the canonical product session.

Routes only expose credential metadata. The raw provider key is accepted once,
sealed server-side, and never returned to the browser or written to logs.
Provider model lists and the connection test are real server-side calls made
with the owner's stored key; they never generate a paid completion.
"""
from __future__ import annotations

import json

from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id
from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .byok_client import CustomProviderError
from .byok_credentials import (
    CUSTOM_PROVIDERS,
    CustomEndpointStorageUnavailable,
    validate_custom_api_key,
)
from .byok_endpoint import CustomEndpointError, normalize_custom_endpoint

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


def _client(request: Request):
    return getattr(request.app.state, "custom_provider_client", None)


def _provider_options() -> list[dict[str, object]]:
    return [
        {
            "provider": spec.provider_id,
            "display_name": spec.display_name,
            "model": spec.model_id,
            "models": list(spec.models),
            "default_endpoint": spec.base_origin,
            "supports_custom_endpoint": True,
            "supports_model_listing": spec.models_path is not None,
            "supports_connection_test": spec.models_path is not None,
            "manual_model": spec.allowed_models is None,
        }
        for spec in CUSTOM_PROVIDERS.values()
    ]


def _unavailable() -> JSONResponse:
    return _error(
        "custom_provider_unavailable",
        "PADIEM Custom을 현재 사용할 수 없습니다.",
        503,
    )


def _provider_error(exc: CustomProviderError) -> JSONResponse:
    return _error(exc.code, exc.user_message, exc.status_code)


async def _read_json_object(request: Request) -> dict | None | JSONResponse:
    try:
        body = await read_bounded_request_body(
            request, max_bytes=MAX_CUSTOM_CREDENTIAL_BODY_BYTES
        )
        raw = json.loads(body.decode("utf-8"))
    except RequestBodyTooLarge:
        return _error("request_too_large", "요청이 너무 큽니다.", 413)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error(
            "custom_credential_request_invalid",
            "요청 형식이 올바르지 않습니다.",
            422,
        )
    if not isinstance(raw, dict):
        return _error(
            "custom_credential_request_invalid",
            "요청 형식이 올바르지 않습니다.",
            422,
        )
    return raw


async def custom_credential_status(request: Request):
    uid = await _owner(request)
    if not uid:
        return _error("authentication_required", "로그인이 필요합니다.", 401)
    store = _store(request)
    if store is None:
        return _unavailable()
    try:
        credentials = await store.status(uid)
    except Exception:
        return _error(
            "custom_credential_unavailable",
            "PADIEM Custom 자격증명을 확인할 수 없습니다.",
            503,
        )
    return JSONResponse(
        {"ok": True, "credentials": credentials, "providers": _provider_options(),
         **({"byok_via_b14": True} if getattr(getattr(request.app.state, "settings", None), "byok_via_b14", False) else {})},
        headers=HEADERS,
    )


async def custom_credential_save(request: Request):
    uid = await _owner(request)
    if not uid:
        return _error("authentication_required", "로그인이 필요합니다.", 401)
    store = _store(request)
    if store is None:
        return _unavailable()
    if request.query_params:
        return _error(
            "custom_credential_request_invalid",
            "요청 형식이 올바르지 않습니다.",
            400,
        )
    raw = await _read_json_object(request)
    if isinstance(raw, JSONResponse):
        return raw
    if set(raw) not in ({"provider", "api_key"}, {"provider", "api_key", "endpoint"}):
        return _error(
            "custom_credential_request_invalid",
            "요청 형식이 올바르지 않습니다.",
            422,
        )
    provider = raw.get("provider")
    spec = CUSTOM_PROVIDERS.get(provider) if isinstance(provider, str) else None
    if spec is None:
        return _error(
            "custom_provider_unsupported",
            "지원하지 않는 PADIEM Custom 공급사입니다.",
            422,
        )
    try:
        api_key = validate_custom_api_key(raw.get("api_key"))
    except ValueError as exc:
        return _error("custom_key_invalid", str(exc), 422)
    endpoint_value = raw.get("endpoint") if "endpoint" in raw else None
    try:
        endpoint = normalize_custom_endpoint(
            endpoint_value, default_endpoint=spec.base_origin
        )
    except CustomEndpointError as exc:
        return _error(exc.code, str(exc), 422)
    try:
        credential = await store.save(
            user_id=uid,
            provider_id=provider,
            api_key=api_key,
            endpoint=endpoint,
        )
    except CustomEndpointStorageUnavailable:
        return _error(
            "custom_endpoint_storage_unavailable",
            "사용자 지정 API 엔드포인트를 저장할 준비가 되지 않았습니다.",
            503,
        )
    except CustomEndpointError as exc:
        return _error(exc.code, str(exc), 422)
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
        return _unavailable()
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


async def custom_provider_models(request: Request):
    uid = await _owner(request)
    if not uid:
        return _error("authentication_required", "로그인이 필요합니다.", 401)
    store = _store(request)
    client = _client(request)
    if store is None or client is None:
        return _unavailable()
    if set(request.query_params.keys()) != {"provider"}:
        return _error(
            "custom_credential_request_invalid",
            "요청 형식이 올바르지 않습니다.",
            400,
        )
    provider = request.query_params.get("provider")
    spec = CUSTOM_PROVIDERS.get(provider) if isinstance(provider, str) else None
    if spec is None:
        return _error(
            "custom_provider_unsupported",
            "지원하지 않는 PADIEM Custom 공급사입니다.",
            422,
        )
    if spec.models_path is None:
        return JSONResponse(
            {
                "ok": True,
                "provider": provider,
                "models": list(spec.models),
                "source": "registry",
            },
            headers=HEADERS,
        )
    try:
        credential = await store.credential(uid, provider)
    except Exception:
        return _error(
            "custom_credential_unavailable",
            "PADIEM Custom 자격증명을 확인할 수 없습니다.",
            503,
        )
    if credential is None:
        return _error(
            "custom_credential_required",
            "PADIEM Custom API 키를 먼저 등록해 주세요.",
            409,
        )
    api_key, endpoint = credential
    try:
        listed = await client.list_models(
            provider_id=provider, api_key=api_key, endpoint=endpoint
        )
    except CustomProviderError as exc:
        return _provider_error(exc)
    except Exception:
        return _error(
            "custom_model_list_failed",
            "공급사 모델 목록을 확인하지 못했습니다.",
            502,
        )
    return JSONResponse(
        {
            "ok": True,
            "provider": provider,
            "models": listed["models"],
            "source": listed["source"],
        },
        headers=HEADERS,
    )


async def custom_credential_test(request: Request):
    uid = await _owner(request)
    if not uid:
        return _error("authentication_required", "로그인이 필요합니다.", 401)
    store = _store(request)
    client = _client(request)
    if store is None or client is None:
        return _unavailable()
    if set(request.query_params.keys()) != {"provider"}:
        return _error(
            "custom_credential_request_invalid",
            "요청 형식이 올바르지 않습니다.",
            400,
        )
    provider = request.query_params.get("provider")
    spec = CUSTOM_PROVIDERS.get(provider) if isinstance(provider, str) else None
    if spec is None:
        return _error(
            "custom_provider_unsupported",
            "지원하지 않는 PADIEM Custom 공급사입니다.",
            422,
        )
    if spec.models_path is None:
        return _error(
            "custom_connection_test_unsupported",
            "이 공급사는 연결 테스트를 지원하지 않습니다.",
            422,
        )
    try:
        credential = await store.credential(uid, provider)
    except Exception:
        return _error(
            "custom_credential_unavailable",
            "PADIEM Custom 자격증명을 확인할 수 없습니다.",
            503,
        )
    if credential is None:
        return _error(
            "custom_credential_required",
            "PADIEM Custom API 키를 먼저 등록해 주세요.",
            409,
        )
    api_key, endpoint = credential
    try:
        checked = await client.test_connection(
            provider_id=provider, api_key=api_key, endpoint=endpoint
        )
    except CustomProviderError as exc:
        return _provider_error(exc)
    except Exception:
        return _error(
            "custom_connection_test_failed",
            "PADIEM Custom 연결을 확인하지 못했습니다.",
            502,
        )
    return JSONResponse(
        {
            "ok": True,
            "provider": provider,
            "models_count": checked["models_count"],
            "source": checked["source"],
        },
        headers=HEADERS,
    )


async def _detect_request(request, *, register=False):
    uid = await _owner(request)
    if not uid:
        return _error("authentication_required", "로그인이 필요합니다.", 401)
    if request.query_params:
        return _error("custom_credential_request_invalid", "요청 형식이 올바르지 않습니다.", 422)
    client, store = _client(request), _store(request)
    if client is None or (register and store is None):
        return _unavailable()
    raw = await _read_json_object(request)
    if isinstance(raw, JSONResponse):
        return raw
    allowed = {"key", "base_url", "provider", "model"} if register else {"key", "base_url"}
    if "key" not in raw or set(raw) - allowed:
        return _error("custom_credential_request_invalid", "요청 형식이 올바르지 않습니다.", 422)
    try:
        key = validate_custom_api_key(raw.get("key"))
    except ValueError:
        return _error("custom_key_invalid", "키 형식을 확인하거나 고급 입력을 이용해 주세요.", 422)
    from .byok_client import detect_byok
    # Registration re-verifies the result instead of trusting a browser's
    # verified flag, endpoint, provider or model. No temporary key store.
    result = await detect_byok(client, key=key, base_url=raw.get("base_url"))
    if not register:
        return JSONResponse(result, headers=HEADERS)
    if not result["verified"]:
        return JSONResponse({"ok": False, **result}, status_code=422, headers=HEADERS)
    provider = result["provider"]
    model = raw.get("model", result["models"][0])
    if (raw.get("provider", provider) != provider or model not in result["models"]):
        return _error("byok_detection_changed", "공급자·모델을 다시 확인해 주세요.", 409)
    try:
        credential = await store.save(user_id=uid, provider_id=provider,
                                       api_key=key, endpoint=result["endpoint"])
    except Exception:
        return _error("custom_credential_save_failed", "키를 저장하지 못했습니다. 고급 입력을 이용해 주세요.", 503)
    return JSONResponse({"ok": True, "credential": credential,
        "selection": {"provider": provider, "model": model}, **result}, headers=HEADERS)


async def byok_detect(request):
    return await _detect_request(request)


async def byok_register(request):
    return await _detect_request(request, register=True)
