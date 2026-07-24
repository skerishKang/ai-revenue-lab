"""BYOK Gateway Pilot UI route."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from app.factory import render_template
from app.pilot.config import pilot_settings
from app.pilot.demo_models import get_pilot_models
from app.pilot.gateway import _validate_provider_key, _validate_chat_request
from app.pilot.schemas import PilotChatRequest
from app.pilot import provider as prv
from app.pilot.errors import PilotError
import logging

logger = logging.getLogger("korean-ai-platform.pilot")
import time
import uuid

router = APIRouter()


def _new_request_id() -> str:
    return f"b14req_{uuid.uuid4().hex[:12]}"


@router.get("/pilot")
async def pilot_page(request: Request):
    return render_template(
        request,
        "pilot.html",
        {
            "pilot_configured": pilot_settings.configured,
            "pilot_models": get_pilot_models(),
            "selected_model": pilot_settings.pilot_model_id or "",
            "prompt": "",
            "result": None,
            "error": None,
        },
    )


@router.post("/pilot")
async def pilot_page_post(
    request: Request,
    provider_key: str = Form(""),
    model_id: str = Form(""),
    prompt: str = Form(""),
    temperature: float = Form(0.2),
    max_tokens: int = Form(300),
):
    if not pilot_settings.configured:
        return render_template(
            request,
            "pilot.html",
            {
                "pilot_configured": False,
                "pilot_models": get_pilot_models(),
                "selected_model": model_id,
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
            _validate_chat_request(chat_req)

            start = time.monotonic()
            response_data = await prv.call_chat_completions(
                api_key=api_key,
                messages=chat_req.messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            latency_ms = int((time.monotonic() - start) * 1000)

            biz14 = response_data.get("business14", {})
            choices = response_data.get("choices", [])
            usage = response_data.get("usage")

            result = {
                "request_id": biz14.get("request_id", f"b14req_{uuid.uuid4().hex[:12]}"),
                "provider": biz14.get("provider", pilot_settings.pilot_provider_id),
                "model": response_data.get("model", model_id),
                "latency_ms": latency_ms,
                "estimated_krw": biz14.get("estimated_krw", 0.0),
                "usage": usage,
                "choices": choices,
            }
        except PilotError as e:
            error = {"code": e.code, "message": e.message, "request_id": _new_request_id()}
        except Exception:
            request_id_e = f"b14req_{uuid.uuid4().hex[:12]}"
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
            "prompt": prompt,
            "result": result,
            "error": error,
        },
    )
