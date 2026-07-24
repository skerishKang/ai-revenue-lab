"""Phase 3: Korean-first session workspace pilot.

Routes:
- GET  /workspace          — Korean-first chat workspace page
- POST /workspace/api/chat  — Proxy to /api/pilot/v1/chat/completions

Design principles:
- Korean-first UI (English optional via ?lang=en)
- Session-only: messages in JS memory, keys in JS memory
- No server-side storage of keys, prompts, or responses
- XSS-safe: all user/assistant content rendered via textContent
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from app.factory import render_template
from app.pilot.config import pilot_settings
from app.pilot.demo_models import get_pilot_models, get_pilot_provider_count, get_pilot_model_count
from app.pilot.gateway import _validate_provider_key, _validate_chat_request
from app.pilot.locale import gettext, locale_from_request, Locale
from app.pilot.errors import PilotError
from app.pilot.schemas import PilotChatRequest
from app.pilot.routing import resolve_configuration, resolve_route, PilotConfigurationState
from app.pilot.registry import get_registry
from app.pilot import provider as prv

logger = logging.getLogger("korean-ai-platform.pilot")

router = APIRouter()

_INVALID_REGISTRY_MESSAGE = "Provider registry 설정이 올바르지 않습니다."


def _new_request_id() -> str:
    import uuid
    return f"b14req_{uuid.uuid4().hex[:12]}"


@router.get("/workspace")
async def workspace_page(request: Request):
    """Korean-first chat workspace page."""
    locale = locale_from_request(request)
    _ = lambda key: gettext(key, locale)  # noqa: E731

    state = resolve_configuration()
    registry = get_registry()

    # Common context with translation function
    base_ctx = {
        "_": lambda key, **kw: gettext(key, locale, **kw),
        "lang": locale.value,
    }

    # Invalid registry
    if state == PilotConfigurationState.INVALID_REGISTRY:
        ctx = dict(base_ctx, **{
            "pilot_configured": False,
            "pilot_models": [],
            "pilot_provider_count": 0,
            "pilot_model_count": 0,
            "pilot_models_json": "[]",
            "error_code_json": json.dumps("registry_invalid"),
            "error": {"code": "registry_invalid", "message": _("error.registry_invalid"), "request_id": _new_request_id()},
        })
        return render_template(request, "workspace.html", ctx)

    # Not configured
    if state == PilotConfigurationState.NOT_CONFIGURED:
        ctx = dict(base_ctx, **{
            "pilot_configured": False,
            "pilot_models": [],
            "pilot_provider_count": 0,
            "pilot_model_count": 0,
            "pilot_models_json": "[]",
            "error_code_json": json.dumps(None),
            "error": None,
        })
        return render_template(request, "workspace.html", ctx)

    # Valid registry or legacy
    models = get_pilot_models()
    models_json = json.dumps(models, ensure_ascii=False)
    ctx = dict(base_ctx, **{
        "pilot_configured": True,
        "pilot_models": models,
        "pilot_provider_count": get_pilot_provider_count(),
        "pilot_model_count": get_pilot_model_count(),
        "pilot_models_json": models_json,
        "error_code_json": json.dumps(None),
        "error": None,
    })
    return render_template(request, "workspace.html", ctx)


@router.post("/workspace/api/chat")
async def workspace_chat(request: Request):
    """Proxy chat completion request to /api/pilot/v1/chat/completions.

    Accepts the same body format as POST /api/pilot/v1/chat/completions
    but extracts the provider key from header.
    """
    request_id = _new_request_id()

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"error": {"code": "invalid_request", "message": "요청 형식이 올바르지 않습니다.", "request_id": request_id}},
        )

    model = body.get("model", "")
    messages = body.get("messages", [])
    temperature = body.get("temperature", 0.2)
    max_tokens = body.get("max_tokens", 512)

    # Validate provider key from header
    raw_key = request.headers.get("X-Business14-Provider-Key", "")
    try:
        api_key = _validate_provider_key(raw_key)
    except PilotError as e:
        return JSONResponse(
            status_code=e.status_code,
            content={"error": {"code": e.code, "message": e.message, "request_id": request_id}},
        )

    # Validate and route
    try:
        route = resolve_route(model)
    except PilotError as e:
        return JSONResponse(
            status_code=e.status_code,
            content={"error": {"code": e.code, "message": e.message, "request_id": request_id}},
        )

    # Build request schema for validation
    try:
        chat_req = PilotChatRequest(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        _validate_chat_request(chat_req)
    except PilotError as e:
        return JSONResponse(
            status_code=e.status_code,
            content={"error": {"code": e.code, "message": e.message, "request_id": request_id}},
        )

    # Call provider
    try:
        import time
        start = time.monotonic()
        response_data = await prv.call_chat_completions(
            api_key=api_key,
            messages=chat_req.messages,
            temperature=temperature,
            max_tokens=max_tokens,
            base_url=route.base_url,
            upstream_model=route.upstream_model,
            timeout_seconds=route.timeout_seconds,
            response_model=route.model_id,
        )
        latency_ms = int((time.monotonic() - start) * 1000)

        response_data.setdefault("business14", {})
        response_data["business14"]["request_id"] = request_id
        response_data["business14"]["latency_ms"] = latency_ms
        response_data["business14"]["estimated_krw"] = None

        return response_data

    except PilotError as e:
        return JSONResponse(
            status_code=e.status_code,
            content={"error": {"code": e.code, "message": e.message, "request_id": request_id}},
        )
    except Exception as e:
        logger.error("workspace_chat_error request_id=%s error=%s", request_id, str(e)[:100])
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "요청을 처리하는 중 내부 오류가 발생했습니다.",
                    "request_id": request_id,
                }
            },
        )
