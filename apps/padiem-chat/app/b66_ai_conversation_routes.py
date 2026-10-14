"""B66 #4466/#4412 authenticated conversation routes: no quote WRITE authority.

The browser may send only the customer's message, the selected exact model and
the last revision it saw. It cannot supply owner/workspace, provider
credentials, quote IDs, CGI template IDs or a pre-classified intent. The server
derives the owner/workspace slot from the session, loads and validates the
conversation state, dispatches one authorized B14 model call, validates the
bounded JSON output and owns every mode transition.

This route never creates, saves, overwrites or issues a quotation. The only
draft-shaped output it can produce is the canonical QuoteCore draft *input*,
returned by an explicit customer approval action (``action="approve_draft"``)
and consumed by the existing client QuoteCore path, which alone computes and
persists the quotation. A model intent can never reach that action. Duplicate
turns are answered from the stored state without a second provider call. Every
write is a revision compare-and-swap, so a stale client and a request that lost
a concurrent race are both refused with 409 instead of mutating: the first
committed state is the durable one and both writers are never told they won.
"""
from __future__ import annotations

import re
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from .b14_client import ChatRuntimeError
from .b66_ai_conversation import (
    ACTION_APPROVE_DRAFT,
    ACTIONS,
    B66ConversationError,
    ConversationRevisionConflict,
    METHOD_FLEXIBLE,
    METHOD_GUIDED,
    SERVER_CANCEL_ANSWER,
    SERVER_CONFIRM_ANSWER,
    SERVER_DRAFT_ANSWER,
    SERVER_METHOD_ANSWERS,
    append_history,
    apply_message_transition,
    approve_draft_transition,
    bump_revision,
    cancel_staged_transition,
    choose_method_transition,
    confirm_transition,
    conversation_prompt,
    empty_state,
    normalize_conversation_state,
    parse_model_output,
    state_summary,
    valid_revision,
)
from .b66_quote_history_routes import _owner_and_workspace
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

_MODEL_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}")
_ALLOWED_FIELDS = frozenset(
    {"model_id", "message", "action", "method", "revision", "reasoning_level"}
)


def _rejection_headers(exc: B66ConversationError) -> dict[str, str]:
    """Bounded structural diagnostics only; customer text never leaks."""
    headers = {}
    reason = str(getattr(exc, "message", "") or "")[:64]
    path = str(getattr(exc, "path", "") or "")[:64]
    observed = str(getattr(exc, "observed_type", "") or "")[:16]
    if re.fullmatch(r"[a-z_]{1,64}", reason):
        headers["X-B66-Conversation-Reason"] = reason
    if path and re.fullmatch(r"[A-Za-z0-9_.\[\]]{1,64}", path):
        headers["X-B66-Conversation-Path"] = path
    if observed and re.fullmatch(r"[a-z]{1,16}", observed):
        headers["X-B66-Conversation-Type"] = observed
    return headers


def _conversation_state_payload(state: dict, *, extra: dict | None = None) -> dict:
    """Bounded response projection. Quote facts only; never a message log."""
    summary = state_summary(state)
    quote = {
        "mode": summary["mode"],
        "method": summary["method"],
        "awaiting_method": summary["awaiting_method"],
        "staged": summary["staged"],
        "approval_required": summary["approval_required"],
        "facts": summary["facts"],
        "missing": summary["missing"],
        "next_question": summary["next_question"],
    }
    if extra:
        quote.update(extra)
    return quote


async def _revision_conflict_response(store: Any, uid: str, workspace_id: str) -> JSONResponse:
    """Bounded 409 for a write that lost the revision race.

    The winner's state stays durable; this response only tells the client which
    revision it must resync to. If the slot cannot be re-read the revision is
    omitted rather than guessed.
    """
    body: dict[str, Any] = {"ok": False, "error": {"code": "revision_conflict"}}
    try:
        stored = await store.load(user_id=uid, workspace_id=workspace_id)
    except Exception:
        stored = None
    if isinstance(stored, dict):
        body["revision"] = stored["revision"]
        body["mode"] = stored["mode"]
    return JSONResponse(body, status_code=409, headers=_NO_STORE)


async def conversation_state(request: Request) -> JSONResponse:
    """GET: the owner-scoped conversation slot, for resume and resync."""
    _clear_reservation()
    uid = _owner(request)
    if uid is None:
        return _error(401, "unauthorized", "로그인이 필요합니다.")
    access, denied = await _member_access(request, uid)
    if denied is not None:
        return denied
    scope = await _owner_and_workspace(request)
    if scope is None:
        return _error(401, "unauthorized", "로그인이 필요합니다.")
    _, workspace_id = scope
    store = getattr(request.app.state, "b66_ai_conversation_store", None)
    if store is None:
        return _error(503, "conversation_state_unavailable", "대화 상태를 불러올 수 없습니다.")
    try:
        state = await store.load(user_id=uid, workspace_id=workspace_id)
    except B66ConversationError:
        return _error(503, "conversation_state_read_failed", "대화 상태를 불러오지 못했습니다.")
    except Exception:
        return _error(503, "conversation_state_read_failed", "대화 상태를 불러오지 못했습니다.")
    if state is None:
        return JSONResponse(
            {"ok": True, "state": None}, headers=_NO_STORE
        )
    return JSONResponse(
        {"ok": True, "state": state_summary(state)}, headers=_NO_STORE
    )


async def conversation_turn(request: Request) -> JSONResponse:
    """POST: one authorized conversation turn. Never issues or mutates a quote."""
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
    if (
        not isinstance(model_id, str)
        or not _MODEL_ID_RE.fullmatch(model_id)
        or model_id == "b14/auto"
        or model_id.startswith("padiem-profile/")
    ):
        return _error(400, "model_selection_required", "사용할 AI 모델을 선택해 주세요.")
    if access is not None:
        if model_id in access["disabled_models"]:
            return _error(403, "model_disabled", "관리자가 이 AI 모델을 사용 중지했습니다.")
        if access["active_policy"] and model_id not in access["model_ids"]:
            return _error(403, "model_tier_forbidden", "이용 등급에서 허용하지 않는 AI 모델입니다.")
    reasoning_level = data.get("reasoning_level")
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
    revision = data.get("revision")
    if not valid_revision(revision):
        return _error(400, "invalid_revision", "대화 상태 버전을 확인해 주세요.")
    action = data.get("action") or "message"
    if action not in ACTIONS:
        return _error(400, "unsupported_action", "지원하지 않는 대화 동작입니다.")
    message = data.get("message")
    method = data.get("method")
    if action == "message":
        if not isinstance(message, str) or not message.strip():
            return _error(400, "invalid_message", "대화 내용을 입력해 주세요.")
        message = message.strip()
        if len(message) > 2_000:
            return _error(400, "message_too_large", "메시지가 너무 깁니다.")
    if action == "choose_method" and method not in (METHOD_FLEXIBLE, METHOD_GUIDED):
        return _error(400, "invalid_method", "작성 방식을 확인해 주세요.")

    scope = await _owner_and_workspace(request)
    if scope is None:
        return _error(401, "unauthorized", "로그인이 필요합니다.")
    _, workspace_id = scope
    store = getattr(request.app.state, "b66_ai_conversation_store", None)
    if store is None:
        return _error(503, "conversation_state_unavailable", "대화 상태를 불러올 수 없습니다.")
    try:
        loaded = await store.load(user_id=uid, workspace_id=workspace_id)
    except Exception:
        return _error(503, "conversation_state_read_failed", "대화 상태를 불러오지 못했습니다.")
    state = loaded if loaded is not None else empty_state()

    if loaded is not None and revision != state["revision"]:
        # A stale client never mutates server state; it must resync first.
        return JSONResponse(
            {"ok": False, "error": {"code": "revision_conflict"},
             "revision": state["revision"], "mode": state["mode"]},
            status_code=409, headers=_NO_STORE,
        )

    # The exact revision this request was built on. Every write below swaps on
    # it, so a request that raced another writer after this read is refused
    # instead of silently overwriting the first committed state.
    expected_revision = state["revision"]

    if action == "message" and loaded is not None and message == state["last_user_message"]:
        # Exact duplicate of the turn this revision already answered: return the
        # stored answer without a second provider call.
        return JSONResponse(
            {"ok": True, "answer": state["last_answer"],
             "answer_origin": state["answer_origin"],
             "model_id": model_id, "revision": state["revision"],
             "mode": state["mode"], "mode_changed": False,
             "quote": _conversation_state_payload(state, extra={"idempotent_replay": True})},
            headers=_NO_STORE,
        )


    if action in ("choose_method", "confirm", "cancel_staged", ACTION_APPROVE_DRAFT):
        # Pure server-state transitions. No model call: a customer control can
        # never be classified by, or depend on, model availability.
        draft = None
        try:
            if action == "choose_method":
                state = choose_method_transition(state, method)
                answer = SERVER_METHOD_ANSWERS[method]
            elif action == "confirm":
                state = confirm_transition(state)
                answer = SERVER_CONFIRM_ANSWER
            elif action == ACTION_APPROVE_DRAFT:
                # The customer's explicit approval produces the QuoteCore draft
                # input. This route never saves, overwrites or issues a
                # quotation: the existing client QuoteCore path owns the
                # calculation and the write after the review screen.
                state, draft = approve_draft_transition(state)
                answer = SERVER_DRAFT_ANSWER
            else:
                state = cancel_staged_transition(state)
                answer = SERVER_CANCEL_ANSWER
        except B66ConversationError:
            return _error(
                400, "conversation_transition_refused", "현재 대화 상태에서 사용할 수 없는 동작입니다."
            )
        state["last_answer"] = answer
        state["answer_origin"] = "server_state"
        state = bump_revision(state)
        try:
            await store.save(
                user_id=uid, workspace_id=workspace_id,
                state=state, expected_revision=expected_revision,
            )
        except ConversationRevisionConflict:
            return await _revision_conflict_response(store, uid, workspace_id)
        except Exception:
            return _error(503, "conversation_state_write_failed", "대화 상태를 저장하지 못했습니다.")
        body = {
            "ok": True, "answer": answer, "answer_origin": "server_state",
            "model_id": model_id, "revision": state["revision"],
            "mode": state["mode"], "mode_changed": False,
            "quote": _conversation_state_payload(state),
        }
        if draft is not None:
            body["draft"] = draft
        return JSONResponse(body, headers=_NO_STORE)

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
            [{"role": "user", "content": message}],
            model=route.model_id,
            additional_system_context=conversation_prompt(state),
            model_parameters=parameters,
        )
    except ChatRuntimeError as exc:
        return _error(exc.status_code, exc.code, exc.user_message)
    except Exception:
        return _error(502, "conversation_execution_failed", "AI 응답을 생성하지 못했습니다.")
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
        return _error(502, "conversation_invalid_answer", "AI 응답을 확인할 수 없습니다.")
    try:
        reply, intent, delta = parse_model_output(result["answer"])
    except B66ConversationError as exc:
        # Fail-closed: the previous state stays untouched and intent is never
        # guessed. The customer sees a bounded failure, not a fabricated reply.
        response = _error(502, "conversation_invalid_answer", "AI 응답을 확인할 수 없습니다.")
        for header_name, header_value in _rejection_headers(exc).items():
            response.headers[header_name] = header_value
        return response
    state = apply_message_transition(state, reply, intent, delta)
    mode_changed = state.pop("_mode_changed", False)
    state = append_history(state, message, reply)
    state["last_user_message"] = message
    state = bump_revision(state)
    try:
        await store.save(
            user_id=uid, workspace_id=workspace_id,
            state=state, expected_revision=expected_revision,
        )
    except ConversationRevisionConflict:
        # Another turn committed while this one was waiting on the model. This
        # turn's paid answer is deliberately not written over that state; the
        # client resyncs to the winner and the customer repeats if it still
        # wants this turn applied.
        return await _revision_conflict_response(store, uid, workspace_id)
    except Exception:
        # The model was already paid for this turn; fail closed rather than
        # silently losing the answer. A retry with the same revision+message is
        # answered idempotently from the previous stored state.
        return _error(503, "conversation_state_write_failed", "대화 상태를 저장하지 못했습니다.")
    return JSONResponse(
        {"ok": True, "answer": reply, "answer_origin": "registered_model_completion",
         "model_id": route.model_id, "model_origin": "registered_model_completion",
         "revision": state["revision"], "mode": state["mode"],
         "mode_changed": mode_changed,
         "quote": _conversation_state_payload(state)},
        headers=_NO_STORE,
    )


__all__ = ["conversation_state", "conversation_turn"]
