"""B66 authenticated natural model conversation: no CGI or QuoteCore write authority.

The browser may send only user/assistant context; it cannot supply system,
owner, scope, provider credentials, quote/Skill IDs or tool actions. Previous
turns are untrusted conversation data, not authoritative persisted quote facts.

#4657 dialogue continuity
    A request may name an existing ``conversation_id``. When it does, the
    server-owned B66 history is the authoritative model context and the browser
    transcript is only the new user turn — a browser cannot supersede stored
    history. The id is validated against the signed-in owner AND the
    server-owned ``PRODUCT_SCOPE_B66`` before any model dispatch, so a B66
    request can never continue (or charge a model call for) a same-account
    Chat/Claw conversation. A completed model-origin answer is appended to that
    same owner-scoped conversation and its stable id is returned; a failed
    upstream leaves no record, and a retried request cannot duplicate the turn.
"""
from __future__ import annotations

import re
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from .b14_client import ChatRuntimeError
from .b66_dialogue_routes import b66_dialogue_store, persist_b66_turn
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
from .b66_search_boundary import _envelope, plan_b66_search
from .dispatch_quota import _clear_reservation, _refund_active_reservation
from .history import HistoryContextIncomplete, validate_conversation_id
from .request_contract import MAX_BROWSER_BODY_BYTES

_ALLOWED_FIELDS = {"model_id", "messages", "reasoning_level", "conversation_id"}


def _valid_turns(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
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


async def _stored_model_messages(
    request: Request, uid: str, conversation_id: str
) -> tuple[list[dict[str, str]] | None, JSONResponse | None]:
    """The owner's stored B66 dialogue as model context, or a bounded refusal.

    ``None`` messages with a response means the dialogue is not this owner's B66
    conversation (404) or its original is unavailable/incomplete (409). It is
    never silently replaced with a fresh context.
    """
    store = b66_dialogue_store(request)
    if store is None:
        return None, _error(503, "dialogue_history_unavailable", "이전 대화를 현재 사용할 수 없습니다.")
    loader = getattr(store, "load_model_context", None)
    if not callable(loader):
        return None, _error(503, "dialogue_history_unavailable", "이전 대화를 현재 사용할 수 없습니다.")
    try:
        stored = await loader(uid, conversation_id)
    except HistoryContextIncomplete:
        return None, _error(
            409, "dialogue_context_incomplete",
            "이전 대화 원문을 불러올 수 없습니다. 새 대화로 다시 시작해 주세요.",
        )
    except Exception:
        return None, _error(503, "dialogue_history_unavailable", "이전 대화를 현재 사용할 수 없습니다.")
    if stored is None:
        return None, _error(404, "conversation_not_found", "대화를 찾을 수 없습니다.")
    messages = stored.get("messages")
    if not isinstance(messages, list):
        return None, _error(409, "dialogue_context_incomplete", "이전 대화 원문을 불러올 수 없습니다.")
    projected = [
        {"role": str(row.get("role", "")), "content": str(row.get("content", ""))}
        for row in messages
        if isinstance(row, dict) and row.get("role") in ("user", "assistant")
        and isinstance(row.get("content"), str) and row["content"].strip()
    ]
    return projected, None


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
    if set(data) - _ALLOWED_FIELDS:
        return _error(400, "unsupported_field", "지원하지 않는 대화 필드입니다.")
    model_id = data.get("model_id")
    messages = data.get("messages")
    reasoning_level = data.get("reasoning_level")
    conversation_id = data.get("conversation_id")
    if conversation_id is not None:
        try:
            valid_conversation_id = validate_conversation_id(conversation_id)
        except ValueError:
            valid_conversation_id = None
        if valid_conversation_id is None:
            return _error(400, "invalid_conversation_id", "대화 참조 형식이 올바르지 않습니다.")
        conversation_id = valid_conversation_id
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

    # The new user turn is the browser's only contribution to a continuation.
    user_text = messages[-1]["content"]
    prior_messages: list[dict[str, str]] = []
    if conversation_id is not None:
        prior_messages, refusal = await _stored_model_messages(request, uid, conversation_id)
        if refusal is not None:
            return refusal
        model_messages = prior_messages + [{"role": "user", "content": user_text}]
    else:
        model_messages = [dict(m) for m in messages]

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

    outcome = await plan_b66_search(
        getattr(request.app.state, "auto_grounding", None),
        user_text,
        # Server state only; a browser field can never authorize paid retrieval.
        # No production bootstrap sets this flag until the #4465 fact-search
        # approval and privacy review have been recorded.
        allow_provider=getattr(request.app.state, "b66_public_fact_search_authorized", False) is True,
    )
    try:
        result = await complete(
            model_messages,
            model=route.model_id,
            additional_system_context=_envelope(outcome),
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

    # Persist only a real model-origin answer, into the same owner- and
    # B66-scoped conversation. A failure here never withholds the answer.
    saved_id = await persist_b66_turn(
        b66_dialogue_store(request),
        uid,
        conversation_id=conversation_id,
        user_text=user_text,
        assistant_text=result["answer"],
        prior_messages=prior_messages,
    )
    body: dict[str, Any] = {
        "ok": True,
        "answer": result["answer"],
        "model_id": route.model_id,
        "saved_quote": False,
        "model_origin": "registered_model_completion",
        "search": outcome.public_dict(),
    }
    if saved_id is not None:
        body["conversation_id"] = saved_id
        body["dialogue_saved"] = True
    return JSONResponse(body, headers=_NO_STORE)


__all__ = ["b66_ai_chat"]
