"""FastAPI router for the BYOK Gateway Pilot API.

Routes:
- GET  /api/pilot/health      — Pilot health check
- GET  /api/pilot/models      — List pilot-available models
- POST /api/pilot/v1/chat/completions — Chat completions via BYOK

All pilot routes require the provider API key in the X-Business14-Provider-Key header.
"""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse

from app.pilot.config import pilot_settings
from app.pilot.errors import (
    InvalidRequest,
    MissingProviderKey,
    PilotError,
    PlaceholderKeyRejected,
    StreamNotSupported,
    ToolsNotSupported,
    UnsupportedModel,
)
from app.pilot import provider as prv
from app.pilot.schemas import PilotChatRequest

logger = logging.getLogger("korean-ai-platform.pilot")

router = APIRouter(prefix="/api/pilot")

# Placeholder patterns to reject
_PLACEHOLDER_PATTERNS = [
    "sk-your",
    "your-api-key",
    "test-key",
    "demo-key",
    "$kap_api_key",
    "placeholder",
]


def _is_placeholder_key(key: str) -> bool:
    lower = key.lower().strip()
    if not key or key == "":
        return False  # empty is handled separately
    for pattern in _PLACEHOLDER_PATTERNS:
        if pattern in lower:
            return True
    if len(key) < 8:
        return True
    return False


def _validate_provider_key(x_business14_provider_key: str | None) -> str:
    if not x_business14_provider_key:
        raise MissingProviderKey()
    if _is_placeholder_key(x_business14_provider_key):
        raise PlaceholderKeyRejected()
    return x_business14_provider_key


def _validate_chat_request(req: PilotChatRequest) -> None:
    if req.stream:
        raise StreamNotSupported()
    if req.tools:
        raise ToolsNotSupported()
    if not req.messages or not isinstance(req.messages, list):
        raise InvalidRequest("messages 필드는 비어 있을 수 없습니다.")
    if not req.model:
        raise InvalidRequest("model 필드는 필수입니다.")
    # Check model support (must be the configured pilot model or the upstream model name)
    supported_models = [pilot_settings.pilot_model_id]
    if pilot_settings.pilot_upstream_model:
        supported_models.append(pilot_settings.pilot_upstream_model)
    if req.model not in supported_models and req.model != pilot_settings.pilot_model_id:
        raise UnsupportedModel(req.model)


@router.get("/health")
async def pilot_health():
    """Pilot health check. Returns 503 if not configured."""
    return {
        "status": "ok" if pilot_settings.configured else "not_configured",
        "mode": "byok-pilot",
        "configured_providers": 1 if pilot_settings.configured else 0,
    }


@router.get("/models")
async def pilot_models():
    """List models available for pilot."""
    if not pilot_settings.configured:
        return {"models": [], "configured": False}

    display_name = pilot_settings.pilot_model_id
    provider_name = pilot_settings.pilot_provider_id

    return {
        "models": [
            {
                "id": pilot_settings.pilot_model_id,
                "name": display_name,
                "provider_id": pilot_settings.pilot_provider_id,
                "provider_name": provider_name,
                "pilot_available": True,
                "input_krw_per_1k": 0.0,
                "output_krw_per_1k": 0.0,
                "tags": ["pilot", "byok"],
            }
        ],
        "configured": True,
    }


@router.post("/v1/chat/completions")
async def pilot_chat_completions(
    request: PilotChatRequest,
    x_business14_provider_key: str | None = Header(None),
):
    """Execute a BYOK chat completion against the configured upstream provider.

    Requires X-Business14-Provider-Key header with a valid API key.
    """
    # Log request metadata (no secrets, no prompts)
    request_id = f"b14req_{uuid.uuid4().hex[:12]}"
    logger.info(
        "pilot_request request_id=%s model=%s messages=%d",
        request_id,
        request.model,
        len(request.messages) if request.messages else 0,
    )

    try:
        api_key = _validate_provider_key(x_business14_provider_key)

        if not pilot_settings.configured:
            from app.pilot.errors import PilotNotConfigured
            raise PilotNotConfigured()

        _validate_chat_request(request)

        start_time = time.monotonic()
        response_data = await prv.call_chat_completions(
            api_key=api_key,
            messages=request.messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )
        latency_ms = int((time.monotonic() - start_time) * 1000)

        # Inject latency and request ID
        response_data.setdefault("business14", {})
        response_data["business14"]["latency_ms"] = latency_ms
        response_data["business14"]["request_id"] = request_id

        logger.info(
            "pilot_success request_id=%s model=%s latency_ms=%d",
            request_id,
            request.model,
            latency_ms,
        )

        return response_data

    except PilotError as e:
        logger.warning(
            "pilot_error request_id=%s code=%s status=%d",
            request_id,
            e.code,
            e.status_code,
        )
        return JSONResponse(
            status_code=e.status_code,
            content={
                "error": {
                    "code": e.code,
                    "message": e.message,
                    "request_id": request_id,
                }
            },
        )
    except Exception as e:
        logger.error(
            "pilot_unexpected_error request_id=%s error=%s",
            request_id,
            str(e),
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "서버 내부 오류가 발생했습니다.",
                    "request_id": request_id,
                }
            },
        )
