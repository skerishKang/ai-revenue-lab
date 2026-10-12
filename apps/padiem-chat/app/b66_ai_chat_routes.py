"""B66 authenticated natural model conversation: no CGI or QuoteCore write authority.

The browser may send only user/assistant context; it cannot supply system,
owner, scope, provider credentials, quote/Skill IDs or tool actions. Previous
turns are untrusted conversation data, not authoritative persisted quote facts.
"""
from __future__ import annotations

import re
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from .b14_client import ChatRuntimeError
from .b66_quote_routes import (
    _authorize_quote_usage,
    _error,
    _json,
    _member_access,
    _model_route_error_response,
    _NO_STORE,
    _owner,
    _reasoning_transport_supported,
)
from .b66_reasoning_level import (
    DEFAULT_REASONING_LEVEL,
    reasoning_parameter_for_request,
    reasoning_transport_available,
    validate_reasoning_level,
)
from .b66_registered_model_boundary import (
    B66ModelRouteError,
    B66QuoteTaskRequirements,
    validate_authorized_route,
)
from .dispatch_quota import _clear_reservation, _refund_active_reservation
from .request_contract import MAX_BROWSER_BODY_BYTES


def _valid_turns(value: Any) -> bool:
    return (
        isinstance(value, list)
        and 1 <= len(value) <= 32
        and len(value) % 2 == 1
        and all(
            isinstance(item, dict)
            and set(item) == {"role", "content"}
            and item.get("role") == ("user" if index % 2 == 0 else "assistant")
            and isinstance(item.get("content"), str)
            and bool(item["content"].strip())
            for index, item in enumerate(value)
        )
    )


async def b66_ai_chat(request: Request) -> JSONResponse:
    """Single authorized B14 dialogue dispatch; **never** issue or modify a quote."""
    _clear_reservation()
    uid = _owner(request)
    if uid is None:
        return _error(401, "unauthorized", "로그인이 필요합니다.")
    access, denied = await _member_access(request, uid)
    if denied is not None:
        return denied
    data = await _json(request, max_body_bytes=MAX_BROWSER_BODY_BYTES)
    if isinstance(data, JSONResponse):
        return data
    if set(data) - {"model_id", "messages", "reasoning_level"}:
        return _error(400, "unsupported_field", "지원하지 않는 대화 필드입니다.")
    model_id = data.get("model_id")
    messages = data.get("messages")
    reasoning_level = data.get("reasoning_level")
    if (
        not isinstance(model_id, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}", model_id)
        or model_id == "b14/auto"
        or model_id.startswith("padiem-profile/")
    ):
        return _error(400, "model_selection_required", "사용할 AI 모델을 선택해 주세요.")
    if not _valid_turns(messages):
        return _error(400, "invalid_messages", "대화 입력을 확인해 주세요.")
    if access is not None:
        if model_id in access["disabled_models"]:
            return _error(403, "model_disabled", "관리자가 이 AI 모델을 사용 중지했습니다.")
        if access["active_policy"] and model_id not in access["model_ids"]:
            return _error(403, "model_tier_forbidden", "이용 등급에서 허용하지 않는 AI 모델입니다.")
    try:
        accepted = validate_reasoning_level(model_id, reasoning_level)
    except ValueError:
        return _error(400, "unsupported_reasoning_level", "선택한 추론 수준을 사용할 수 없습니다.")
    parameters = None
    if accepted is not None and accepted != DEFAULT_REASONING_LEVEL:
        if not reasoning_transport_available(
            model_id, transport_supported=_reasoning_transport_supported(request)
        ):
            return _error(422, "reasoning_level_unavailable", "선택한 추론 수준을 전달할 수 없습니다.")
        try:
            parameters = reasoning_parameter_for_request(model_id, accepted)
        except ValueError:
            return _error(422, "reasoning_level_unavailable", "선택한 추론 수준을 전달할 수 없습니다.")

    resolver = getattr(request.app.state, "b66_quote_model_resolver", None)
    resolve = getattr(resolver, "resolve_quote_model", None)
    client = getattr(request.app.state, "b14_client", None)
    complete = getattr(client, "complete_registered_b66_chat_model", None)
    if not callable(resolve) or not callable(complete):
        return _error(503, "ai_chat_unavailable", "AI 대화 실행 경로가 준비되지 않았습니다.")
    denied = await _authorize_quote_usage(request, uid)
    if denied is not None:
        return denied
    requirements = B66QuoteTaskRequirements(selected_model_id=model_id)
    try:
        ready = getattr(client, "ensure_registered_quote_runtime_available", None)
        if not callable(ready):
            await _refund_active_reservation()
            return _error(503, "ai_chat_unavailable", "AI 대화 실행 경로가 준비되지 않았습니다.")
        ready()
        route = validate_authorized_route(await resolve(requirements), requirements)
    except B66ModelRouteError as exc:
        await _refund_active_reservation()
        return _model_route_error_response(exc)
    except Exception:
        await _refund_active_reservation()
        return _error(503, "ai_chat_unavailable", "AI 모델을 사용할 수 없습니다.")

    try:
        result = await complete(
            [dict(m) for m in messages],
            model=route.model_id,
            model_parameters=parameters,
        )
    except ChatRuntimeError as exc:
        return _error(exc.status_code, exc.code, exc.user_message)
    except Exception:
        return _error(502, "ai_chat_execution_failed", "AI 응답을 생성하지 못했습니다.")
    finally:
        await _refund_active_reservation()
    if (
        not isinstance(result, dict)
        or not isinstance(result.get("answer"), str)
        or not result["answer"].strip()
        or not isinstance(result.get("route"), dict)
        or result["route"].get("model") != route.model_id
        or result["route"].get("mode") != "manual"
    ):
        return _error(502, "ai_chat_invalid_answer", "AI 응답을 확인할 수 없습니다.")
    return JSONResponse(
        {"ok": True, "answer": result["answer"], "model_id": route.model_id,
         "saved_quote": False, "model_origin": "registered_model_completion"},
        headers=_NO_STORE,
    )


__all__ = ["b66_ai_chat"]
