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

from starlette.routing import Router
from starlette.responses import JSONResponse
from starlette.requests import Request

from app.pilot.config import pilot_settings
from app.pilot.errors import (
    InvalidRequest,
    MissingProviderKey,
    PlaceholderKeyRejected,
    PilotError,
    StreamNotSupported,
    ToolsNotSupported,
)
from app.pilot.redaction import redact_sensitive
from app.pilot.registry import get_registry
from app.pilot.routing import (
    PilotConfigurationState,
    resolve_configuration,
    resolve_route,
)
from app.pilot.schemas import PilotChatRequest

from app.pilot import provider as prv

logger = logging.getLogger("korean-ai-platform.pilot")

router = Router()

_INVALID_REGISTRY_MESSAGE = "Provider registry 설정이 올바르지 않습니다."


# Allowed fields for PilotChatRequest (dataclass field names)
_VALID_ROLES = frozenset({"system", "user", "assistant"})
_ALLOWED_CHAT_FIELDS = frozenset({
    "model", "messages", "temperature", "max_tokens", "stream", "tools",
})
_ALLOWED_MESSAGE_FIELDS = frozenset({"role", "content"})


class _InvalidBody(PilotError):
    """Request body validation error → HTTP 422."""

    def __init__(self, message: str) -> None:
        super().__init__(code="invalid_body", message=message, status_code=422)


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


def _validate_body(raw: Any) -> dict:
    """Deep-validate and normalize a chat completions JSON body → 422 on failure."""
    if not isinstance(raw, dict):
        raise _InvalidBody("Request body must be a JSON object")

    extra = set(raw) - _ALLOWED_CHAT_FIELDS
    if extra:
        raise _InvalidBody(f"Unexpected top-level fields: {', '.join(sorted(extra))}")

    # model
    if not isinstance(raw.get("model"), str) or not raw["model"].strip():
        raise _InvalidBody("model must be a non-empty string")

    model = raw["model"].strip()
    if len(model) > 200:
        raise _InvalidBody("model must not exceed 200 characters")

    # messages
    msgs = raw.get("messages")
    if not isinstance(msgs, list):
        raise _InvalidBody("messages must be a non-empty array")
    if len(msgs) < 1 or len(msgs) > 100:
        raise _InvalidBody("messages must have 1–100 items")

    validated_messages: list[dict[str, str]] = []
    for i, msg in enumerate(msgs):
        if not isinstance(msg, dict):
            raise _InvalidBody(f"messages[{i}] must be a JSON object")
        m_extra = set(msg) - _ALLOWED_MESSAGE_FIELDS
        if m_extra:
            raise _InvalidBody(f"messages[{i}] unexpected fields: {', '.join(sorted(m_extra))}")
        role = msg.get("role")
        if role not in _VALID_ROLES:
            raise _InvalidBody(f"messages[{i}] role must be one of system/user/assistant")
        content = msg.get("content")
        if not isinstance(content, str) or not content.strip():
            raise _InvalidBody(f"messages[{i}] content must be a non-empty string")
        content = content.strip()
        if len(content) > 32000:
            raise _InvalidBody(f"messages[{i}] content must not exceed 32000 characters")
        validated_messages.append({"role": role, "content": content})

    # temperature
    temp = raw.get("temperature")
    if temp is not None:
        if isinstance(temp, bool) or not isinstance(temp, (int, float)):
            raise _InvalidBody("temperature must be a number or null")
        temp = float(temp)
        if temp < 0.0 or temp > 2.0:
            raise _InvalidBody("temperature must be between 0.0 and 2.0")

    # max_tokens
    mt = raw.get("max_tokens")
    if mt is not None:
        if isinstance(mt, bool) or not isinstance(mt, int):
            raise _InvalidBody("max_tokens must be an integer or null")
        if mt < 1 or mt > 4096:
            raise _InvalidBody("max_tokens must be between 1 and 4096")

    # stream
    st = raw.get("stream")
    if st is not None and not isinstance(st, bool):
        raise _InvalidBody("stream must be a boolean or null")
    if st:
        raise StreamNotSupported()

    # tools
    tl = raw.get("tools")
    if tl is not None:
        if not isinstance(tl, list):
            raise _InvalidBody("tools must be an array or null")
        raise ToolsNotSupported()

    return {
        "model": model,
        "messages": validated_messages,
        "temperature": float(temp) if temp is not None else 0.2,
        "max_tokens": int(mt) if mt is not None else 300,
    }


@router.route("/health", methods=["GET"])
async def pilot_health(request: Request):
    """Pilot health check. Uses routing.resolve_configuration()."""
    state = resolve_configuration()

    if state == PilotConfigurationState.VALID_REGISTRY:
        registry = get_registry()
        return JSONResponse({
            "status": "ok",
            "mode": "byok-multi-provider-pilot",
            "configured_providers": registry.provider_count,
            "configured_models": registry.model_count,
            "providers": registry.provider_summary(),
        })

    if state == PilotConfigurationState.INVALID_REGISTRY:
        return _registry_invalid_response()

    if state == PilotConfigurationState.LEGACY:
        return JSONResponse({
            "status": "ok",
            "mode": "byok-pilot",
            "configured_providers": 1,
            "configured_models": 1,
        })

    return JSONResponse({
        "status": "not_configured",
        "mode": "not_configured",
        "configured_providers": 0,
        "configured_models": 0,
    })


@router.route("/models", methods=["GET"])
async def pilot_models(request: Request):
    """List models available for pilot (multi-provider if configured)."""
    state = resolve_configuration()

    if state == PilotConfigurationState.VALID_REGISTRY:
        registry = get_registry()
        return JSONResponse({
            "models": registry.list_models(),
            "configured": True,
            "mode": "multi-provider",
        })

    if state == PilotConfigurationState.INVALID_REGISTRY:
        return _registry_invalid_response()

    if state == PilotConfigurationState.LEGACY:
        display_name = pilot_settings.pilot_model_id
        provider_name = pilot_settings.pilot_provider_id
        return JSONResponse({
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
        })

    return JSONResponse({"models": [], "configured": False})


@router.route("/v1/chat/completions", methods=["POST"])
async def pilot_chat_completions(
    request: Request,
):
    """Execute a BYOK chat completion with multi-provider routing."""
    request_id = f"b14req_{uuid.uuid4().hex[:12]}"
    logger.info(
        "pilot_request request_id=%s",
        request_id,
    )

    try:
        x_business14_provider_key = request.headers.get("x-business14-provider-key")
        raw_body = await request.json()

        body = _validate_body(raw_body)
        api_key = _validate_provider_key(x_business14_provider_key)

        route = resolve_route(body["model"])

        state = resolve_configuration()
        mode = "byok-multi-provider-pilot" if state == PilotConfigurationState.VALID_REGISTRY else "byok-pilot"

        logger.info(
            "pilot_route request_id=%s model=%s provider=%s state=%s",
            request_id,
            body["model"],
            route.provider_id,
            state.value,
        )

        start_time = time.monotonic()
        response_data = await prv.call_chat_completions(
            api_key=api_key,
            messages=body["messages"],
            temperature=body.get("temperature"),
            max_tokens=body.get("max_tokens"),
            base_url=route.base_url,
            upstream_model=route.upstream_model,
            timeout_seconds=route.timeout_seconds,
            response_model=route.model_id,
        )
        latency_ms = int((time.monotonic() - start_time) * 1000)

        response_data.setdefault("business14", {})
        response_data["business14"]["mode"] = mode
        response_data["business14"]["provider"] = route.provider_id
        response_data["business14"]["model_route"] = body["model"]
        response_data["business14"]["latency_ms"] = latency_ms
        response_data["business14"]["request_id"] = request_id
        response_data["business14"]["estimated_krw"] = None

        logger.info(
            "pilot_success request_id=%s mode=%s latency_ms=%d",
            request_id,
            mode,
            latency_ms,
        )

        return JSONResponse(response_data)

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
