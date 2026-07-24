"""FastAPI router for the BYOK Gateway Pilot API (Phase 2).

Routes:
- GET  /api/pilot/health      — Pilot health check (multi-provider if configured)
- GET  /api/pilot/models      — List pilot-available models
- POST /api/pilot/v1/chat/completions — Chat completions via BYOK with routing

Supports multi-provider registry and legacy single-provider fallback.
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
    RegistryInvalid,
    ModelNotFound,
    ModelDisabled,
    PilotNotConfigured,
)
from app.pilot.routing import resolve_configuration, resolve_route, PilotConfigurationState
from app.pilot import provider as prv
from app.pilot.redaction import redact_sensitive
from app.pilot.schemas import PilotChatRequest
from app.pilot.registry import get_registry

logger = logging.getLogger("korean-ai-platform.pilot")

router = APIRouter(prefix="/api/pilot")


_INVALID_REGISTRY_MESSAGE = "Provider registry 설정이 올바르지 않습니다."


def _new_request_id() -> str:
    return f"b14req_{uuid.uuid4().hex[:12]}"


def _registry_invalid_response() -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "registry_invalid",
                "message": _INVALID_REGISTRY_MESSAGE,
                "request_id": _new_request_id(),
            }
        },
    )


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
        return False
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


@router.get("/health")
async def pilot_health():
    """Pilot health check. Returns configured provider summary.

    Uses routing.resolve_configuration() as single source of truth.
    """
    state = resolve_configuration()

    if state == PilotConfigurationState.VALID_REGISTRY:
        registry = get_registry()
        return {
            "status": "ok",
            "mode": "byok-multi-provider-pilot",
            "configured_providers": registry.provider_count,
            "configured_models": registry.model_count,
            "providers": registry.provider_summary(),
        }

    if state == PilotConfigurationState.INVALID_REGISTRY:
        return _registry_invalid_response()

    if state == PilotConfigurationState.LEGACY:
        return {
            "status": "ok",
            "mode": "byok-pilot",
            "configured_providers": 1,
            "configured_models": 1,
        }

    return {
        "status": "not_configured",
        "mode": "not_configured",
        "configured_providers": 0,
        "configured_models": 0,
    }


@router.get("/models")
async def pilot_models():
    """List models available for pilot (multi-provider if configured).

    Uses routing.resolve_configuration() as single source of truth.
    """
    state = resolve_configuration()

    if state == PilotConfigurationState.VALID_REGISTRY:
        registry = get_registry()
        return {
            "models": registry.list_models(),
            "configured": True,
            "mode": "multi-provider",
        }

    if state == PilotConfigurationState.INVALID_REGISTRY:
        return _registry_invalid_response()

    if state == PilotConfigurationState.LEGACY:
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
                    "input_krw_per_1k": None,
                    "output_krw_per_1k": None,
                    "tags": ["pilot", "byok"],
                }
            ],
            "configured": True,
            "mode": "single-provider",
        }

    return {"models": [], "configured": False}


@router.post("/v1/chat/completions")
async def pilot_chat_completions(
    request: PilotChatRequest,
    x_business14_provider_key: str | None = Header(None),
):
    """Execute a BYOK chat completion with multi-provider routing.

    Determines the target provider from the requested model ID,
    then calls the upstream via the provider adapter.

    Requires X-Business14-Provider-Key header with a valid API key.
    """
    request_id = f"b14req_{uuid.uuid4().hex[:12]}"
    logger.info(
        "pilot_request request_id=%s model=%s messages=%d",
        request_id,
        request.model,
        len(request.messages) if request.messages else 0,
    )

    try:
        api_key = _validate_provider_key(x_business14_provider_key)
        _validate_chat_request(request)

        if not request.model:
            raise InvalidRequest("model 필드는 필수입니다.")

        # Determine routing using configuration resolver
        route = resolve_route(request.model)

        state = resolve_configuration()
        if state == PilotConfigurationState.VALID_REGISTRY:
            mode = "byok-multi-provider-pilot"
        else:
            mode = "byok-pilot"

        logger.info(
            "pilot_route request_id=%s model=%s provider=%s state=%s",
            request_id,
            request.model,
            route.provider_id,
            state.value,
        )

        start_time = time.monotonic()
        response_data = await prv.call_chat_completions(
            api_key=api_key,
            messages=request.messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            base_url=route.base_url,
            upstream_model=route.upstream_model,
            timeout_seconds=route.timeout_seconds,
            response_model=route.model_id,
        )
        latency_ms = int((time.monotonic() - start_time) * 1000)

        response_data.setdefault("business14", {})
        response_data["business14"]["mode"] = mode
        response_data["business14"]["provider"] = route.provider_id
        response_data["business14"]["model_route"] = request.model
        response_data["business14"]["latency_ms"] = latency_ms
        response_data["business14"]["request_id"] = request_id
        response_data["business14"]["estimated_krw"] = None

        logger.info(
            "pilot_success request_id=%s mode=%s latency_ms=%d",
            request_id,
            mode,
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
            redact_sensitive(str(e)),
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "요청을 처리하는 중 내부 오류가 발생했습니다. Request ID로 관리자에게 문의하십시오.",
                    "request_id": request_id,
                }
            },
        )
