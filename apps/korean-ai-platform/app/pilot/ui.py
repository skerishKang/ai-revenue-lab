"""BYOK Gateway Pilot UI route (Phase 2).

Supports multi-provider registry and legacy single-provider fallback.
"""

from __future__ import annotations

from starlette.routing import Router
from starlette.requests import Request
from app.factory import render_template
from app.pilot.config import pilot_settings
from app.pilot.demo_models import get_pilot_models, get_pilot_provider_count, get_pilot_model_count
from app.pilot.gateway import _validate_provider_key
from app.pilot.schemas import PilotChatRequest
from app.pilot import provider as prv
from app.pilot.errors import (
    PilotError,
    PilotNotConfigured,
    ModelNotFound,
    InvalidRequest,
    StreamNotSupported,
    ToolsNotSupported,
    RegistryInvalid,
)
from app.pilot.registry import get_registry
from app.pilot.routing import resolve_configuration, resolve_route, PilotConfigurationState
import logging

logger = logging.getLogger("korean-ai-platform.pilot")
import time
import uuid

router = Router()


def _new_request_id() -> str:
    return f"b14req_{uuid.uuid4().hex[:12]}"


def _validate_chat_request_ui(req: PilotChatRequest) -> None:
    """Simple UI-side validation before calling backend."""
    if req.stream:
        raise StreamNotSupported()
    if req.tools:
        raise ToolsNotSupported()
    if not req.messages:
        raise InvalidRequest("messages 필드는 비어 있을 수 없습니다.")
    if not req.model:
        raise InvalidRequest("model 필드는 필수입니다.")


@router.route("/pilot", methods=["GET"])
async def pilot_page(request: Request):
    state = resolve_configuration()
    registry = get_registry()
    mode_name = state.value if state else "not_configured"

    if state == PilotConfigurationState.INVALID_REGISTRY:
        return render_template(
            request,
            "pilot.html",
            {
                "pilot_configured": False,
                "pilot_models": [],
                "selected_model": "",
                "pilot_provider_count": 0,
                "pilot_model_count": 0,
                "mode_name": "invalid_registry",
                "is_multi_provider": False,
                "prompt": "",
                "result": None,
                "error": {
                    "code": "registry_invalid",
                    "message": "Provider registry 설정이 올바르지 않습니다.",
                    "request_id": _new_request_id(),
                },
            },
        )

    return render_template(
        request,
        "pilot.html",
        {
            "pilot_configured": state in (PilotConfigurationState.VALID_REGISTRY, PilotConfigurationState.LEGACY),
            "pilot_models": get_pilot_models(),
            "selected_model": pilot_settings.pilot_model_id or "",
            "pilot_provider_count": get_pilot_provider_count(),
            "pilot_model_count": get_pilot_model_count(),
            "mode_name": mode_name,
            "is_multi_provider": state == PilotConfigurationState.VALID_REGISTRY,
            "prompt": "",
            "result": None,
            "error": None,
        },
    )


@router.route("/pilot", methods=["POST"])
async def pilot_page_post(
    request: Request,
):
    form = await request.form()
    provider_key = form.get("provider_key", "")
    model_id = form.get("model_id", "")
    prompt = form.get("prompt", "")
    temperature = float(form.get("temperature", 0.2))
    max_tokens = int(form.get("max_tokens", 300))
    state = resolve_configuration()

    if state == PilotConfigurationState.INVALID_REGISTRY:
        registry = get_registry()
        return render_template(
            request,
            "pilot.html",
            {
                "pilot_configured": False,
                "pilot_models": [],
                "selected_model": model_id,
                "pilot_provider_count": 0,
                "pilot_model_count": 0,
                "mode_name": "invalid_registry",
                "is_multi_provider": False,
                "prompt": prompt,
                "result": None,
                "error": {
                    "code": "registry_invalid",
                    "message": "Provider registry 설정이 올바르지 않습니다.",
                    "request_id": _new_request_id(),
                },
            },
        )

    if state == PilotConfigurationState.NOT_CONFIGURED:
        return render_template(
            request,
            "pilot.html",
            {
                "pilot_configured": False,
                "pilot_models": get_pilot_models(),
                "selected_model": model_id,
                "pilot_provider_count": 0,
                "pilot_model_count": 0,
                "mode_name": "not_configured",
                "is_multi_provider": False,
                "prompt": prompt,
                "result": None,
                "error": {"code": "pilot_not_configured", "message": "Pilot Provider가 설정되지 않았습니다.", "request_id": _new_request_id()},
            },
        )

    result = None
    error = None

    if not provider_key.strip():
        error = {"code": "missing_key", "message": "Provider API key를 입력하십시오.", "request_id": _new_request_id()}
    elif not prompt.strip():
        error = {"code": "missing_prompt", "message": "Prompt를 입력하십시오.", "request_id": _new_request_id()}
    else:
        try:
            api_key = _validate_provider_key(provider_key)
            chat_req = PilotChatRequest(
                model=model_id or pilot_settings.pilot_model_id,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            _validate_chat_request_ui(chat_req)

            # Determine routing target via resolver
            target = resolve_route(chat_req.model)

            start = time.monotonic()
            response_data = await prv.call_chat_completions(
                api_key=api_key,
                messages=chat_req.messages,
                temperature=temperature,
                max_tokens=max_tokens,
                base_url=target.base_url,
                upstream_model=target.upstream_model,
                timeout_seconds=target.timeout_seconds,
                response_model=target.model_id,
            )
            latency_ms = int((time.monotonic() - start) * 1000)

            biz14 = response_data.get("business14", {})
            choices = response_data.get("choices", [])
            usage = response_data.get("usage")

            result = {
                "request_id": biz14.get("request_id", _new_request_id()),
                "provider": target.provider_id,
                "model": biz14.get("model", chat_req.model),
                "latency_ms": latency_ms,
                "estimated_krw": None,
                "usage": usage,
                "choices": choices,
            }
        except PilotError as e:
            error = {"code": e.code, "message": e.message, "request_id": _new_request_id()}
        except Exception:
            request_id_e = _new_request_id()
            logger.error("pilot_ui_error request_id=%s", request_id_e)
            error = {
                "code": "internal_error",
                "message": "요청을 처리하는 중 내부 오류가 발생했습니다. Request ID로 관리자에게 문의하십시오.",
                "request_id": request_id_e,
            }

    return render_template(
        request,
        "pilot.html",
        {
            "pilot_configured": pilot_settings.configured,
            "pilot_models": get_pilot_models(),
            "selected_model": model_id or pilot_settings.pilot_model_id,
            "pilot_provider_count": get_pilot_provider_count(),
            "pilot_model_count": get_pilot_model_count(),
            "mode_name": pilot_settings.mode_name,
            "is_multi_provider": get_registry().configured,
            "prompt": prompt,
            "result": result,
            "error": error,
        },
    )
