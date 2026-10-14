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
    upstream leaves no record.

#4657 retry safety
    A retry must not append a second exchange and must not repeat a paid model
    dispatch. Three mechanisms, in order, and none of them compares assistant
    prose for identity:

    1. SYNC/RECONCILE before dispatch. The browser transcript length is compared
       with the stored dialogue length. A client that is *behind* the stored
       dialogue is replaying a turn the server already holds: the stored answer
       is returned with no model call and no append. Any other mismatch (client
       ahead, or behind for a different last turn) is an ambiguous retry and is
       refused with a bounded 409 **before** any model dispatch.
    2. SINGLE-FLIGHT per (owner, conversation). Concurrent duplicates of the same
       turn are serialised, so the second observes the first one's committed turn
       and takes the reconcile path instead of dispatching again.
    3. ATOMIC COMMIT. The canonical store's ``messages`` table is unique on
       ``(conversation_id, sequence_number)``, so two writers that computed the
       same next sequence cannot both commit; the loser adds no message pair.
       The stored tail is re-read after the dispatch, so a turn that landed while
       the model ran is reported as a replay rather than appended twice.

    A brand-new conversation has no stored dialogue to reconcile against, so the
    browser sends an opaque ``turn_token`` per submission (reused for that
    submission's transport retries). A repeated token resolves to the
    conversation it already created, with no second model call. That recall is
    in-isolate and bounded, not durable: a cross-isolate duplicate of a *first*
    turn is not deduplicated here and would need a durable attempt identity in
    storage (a new migration), which this change deliberately does not add.
"""
from __future__ import annotations

import asyncio
import re
from collections import OrderedDict
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

_ALLOWED_FIELDS = {"model_id", "messages", "reasoning_level", "conversation_id", "turn_token"}

_TURN_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")

# In-isolate only, bounded: single-flight for duplicate turns and a recall of the
# conversation a first turn already created. See the module docstring.
_INFLIGHT_TURNS: set[tuple[str, str]] = set()
_TURN_POLL_SECONDS = 0.005
# No fixed ceiling: a duplicate must wait for the first model dispatch to finish
# no matter how slow the provider is, instead of timing out and dispatching again.
_TURN_POLL_LIMIT = None
_RECENT_TURNS: "OrderedDict[tuple[str, str], str]" = OrderedDict()
_RECENT_TURN_LIMIT = 512

_REPLAY_SEARCH = {"status": "replay", "reason": "idempotent_replay", "sources": []}
_OUT_OF_SYNC = (
    "dialogue_out_of_sync",
    "이전 대화 상태가 서버와 다릅니다. 대화를 다시 열어 주세요.",
)
_ALREADY_RECORDED = (
    "dialogue_turn_already_recorded",
    "같은 질문을 방금 보내셨습니다. 질문을 조금 바꾸거나 이전 대화를 다시 열어 주세요.",
)


def reset_dialogue_idempotency() -> None:
    """Drop the in-isolate single-flight state (test seam)."""
    _INFLIGHT_TURNS.clear()
    _RECENT_TURNS.clear()


async def _wait_for_duplicate_turn(key: tuple[str, str]) -> bool:
    """Yield until an in-flight duplicate of this turn has landed.

    There is deliberately **no** fixed timeout. Returning while the key is still
    marked in-flight lets the caller dispatch a second, duplicate paid model
    call, which is exactly the charge the idempotency contract forbids; a slow
    first model response cannot be allowed to turn into a second dispatch.

    Deliberately not an ``asyncio.Lock``: a lock binds to the event loop that
    first awaited it, while every Worker request is served on its own loop, so a
    shared lock would raise instead of guarding.
    """
    while key in _INFLIGHT_TURNS:
        await asyncio.sleep(_TURN_POLL_SECONDS)
    return True


def _remember_turn(owner: str, token: str | None, conversation_id: str) -> None:
    if not token:
        return
    key = (owner, token)
    _RECENT_TURNS[key] = conversation_id
    _RECENT_TURNS.move_to_end(key)
    while len(_RECENT_TURNS) > _RECENT_TURN_LIMIT:
        _RECENT_TURNS.popitem(last=False)


def _recalled_turn(owner: str, token: str | None) -> str | None:
    if not token:
        return None
    return _RECENT_TURNS.get((owner, token))


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


def _completed_tail(messages: list[dict[str, str]]) -> tuple[str, str] | None:
    """The last (user, assistant) pair when the dialogue ends with a completed one."""
    if len(messages) < 2:
        return None
    last, previous = messages[-1], messages[-2]
    if last.get("role") != "assistant" or previous.get("role") != "user":
        return None
    return previous.get("content", ""), last.get("content", "")


def _replay_response(*, conversation_id: str, model_id: str, answer: str) -> JSONResponse:
    return JSONResponse(
        {
            "ok": True,
            "answer": answer,
            "model_id": model_id,
            "saved_quote": False,
            "model_origin": "registered_model_completion",
            "search": dict(_REPLAY_SEARCH),
            "conversation_id": conversation_id,
            "dialogue_saved": True,
            "dialogue_replay": True,
        },
        headers=_NO_STORE,
    )


def _out_of_sync() -> JSONResponse:
    return _error(409, _OUT_OF_SYNC[0], _OUT_OF_SYNC[1])


def _already_recorded() -> JSONResponse:
    return _error(409, _ALREADY_RECORDED[0], _ALREADY_RECORDED[1])


async def _stored_model_messages(
    store: Any, uid: str, conversation_id: str,
) -> tuple[list[dict[str, str]] | None, JSONResponse | None]:
    """The owner's stored B66 dialogue as model context, or a bounded refusal.

    ``None`` messages with a response means the dialogue is not this owner's B66
    conversation (404) or its original is unavailable/incomplete (409). It is
    never silently replaced with a fresh context.
    """
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
    turn_token = data.get("turn_token")
    if conversation_id is not None:
        try:
            valid_conversation_id = validate_conversation_id(conversation_id)
        except ValueError:
            valid_conversation_id = None
        if valid_conversation_id is None:
            return _error(400, "invalid_conversation_id", "대화 참조 형식이 올바르지 않습니다.")
        conversation_id = valid_conversation_id
    if turn_token is not None and (
        not isinstance(turn_token, str) or not _TURN_TOKEN_RE.fullmatch(turn_token)
    ):
        return _error(400, "invalid_turn_token", "대화 시도 참조 형식이 올바르지 않습니다.")
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
    client_prior_len = len(messages) - 1
    store = b66_dialogue_store(request)

    if conversation_id is None:
        # A first turn has no stored dialogue to reconcile against; an opaque
        # per-submission token is the only retry identity available here.
        recalled = _recalled_turn(uid, turn_token)
        if recalled is not None and store is not None:
            stored_messages, _refusal = await _stored_model_messages(store, uid, recalled)
            tail = _completed_tail(stored_messages or []) if stored_messages is not None else None
            if tail is not None and tail[0] == user_text:
                return _replay_response(
                    conversation_id=recalled, model_id=model_id, answer=tail[1],
                )
        lock_key = (uid, "new:" + (turn_token or ""))
    else:
        lock_key = (uid, conversation_id)

    # Duplicates of the same turn are single-flighted inside this isolate, so a
    # concurrent retry observes the first one's committed turn instead of
    # dispatching a second model call.
    claimed = False
    if lock_key in _INFLIGHT_TURNS:
        await _wait_for_duplicate_turn(lock_key)
    else:
        _INFLIGHT_TURNS.add(lock_key)
        claimed = True
    try:
        prior_messages: list[dict[str, str]] = []
        if conversation_id is not None:
            prior_messages, refusal = await _stored_model_messages(store, uid, conversation_id)
            if refusal is not None:
                return refusal
            stored_len = len(prior_messages)
            tail = _completed_tail(prior_messages)
            if client_prior_len > stored_len:
                # The browser claims turns the server never stored. Never guess:
                # refuse before dispatching so no context is silently invented.
                return _out_of_sync()
            if tail is not None and tail[0] == user_text:
                # The dialogue's last recorded user turn is exactly this one.
                if client_prior_len < stored_len:
                    # ...and the browser is behind that recorded turn, so this is a
                    # replay of a turn the server already applied. Serve the stored
                    # answer: no second model call, no second exchange.
                    return _replay_response(
                        conversation_id=conversation_id, model_id=model_id, answer=tail[1],
                    )
                # Otherwise it is ambiguous — the customer repeated the last message,
                # or a client that sends no history is replaying it. Refuse before
                # any dispatch instead of inventing context or paying twice.
                return _already_recorded()
            model_messages = prior_messages + [{"role": "user", "content": user_text}]
        else:
            # A first-turn duplicate that lost the race must re-check token recall
            # AFTER waiting: the winner has now stored and remembered the token,
            # so this request must replay instead of dispatching again.
            if not claimed and turn_token is not None:
                recalled = _recalled_turn(uid, turn_token)
                if recalled is not None and store is not None:
                    stored_messages, _refusal = await _stored_model_messages(store, uid, recalled)
                    tail = _completed_tail(stored_messages or []) if stored_messages is not None else None
                    if tail is not None and tail[0] == user_text:
                        return _replay_response(
                            conversation_id=recalled, model_id=model_id, answer=tail[1],
                        )
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
        answer = result["answer"]

        if conversation_id is not None:
            # A duplicate that landed while the model ran wins: the turn is
            # already recorded, so report it rather than append a second pair.
            latest, refusal = await _stored_model_messages(store, uid, conversation_id)
            if refusal is None and latest is not None and len(latest) > len(prior_messages):
                landed = _completed_tail(latest)
                if landed is not None and landed[0] == user_text:
                    return _replay_response(
                        conversation_id=conversation_id, model_id=model_id, answer=landed[1],
                    )

        # Persist only a real model-origin answer, into the same owner- and
        # B66-scoped conversation. A failure here never withholds the answer.
        saved_id = await persist_b66_turn(
            store,
            uid,
            conversation_id=conversation_id,
            user_text=user_text,
            assistant_text=answer,
        )
        if saved_id is not None:
            _remember_turn(uid, turn_token, saved_id)
        body: dict[str, Any] = {
            "ok": True,
            "answer": answer,
            "model_id": route.model_id,
            "saved_quote": False,
            "model_origin": "registered_model_completion",
            "search": outcome.public_dict(),
        }
        if saved_id is not None:
            body["conversation_id"] = saved_id
            body["dialogue_saved"] = True
        return JSONResponse(body, headers=_NO_STORE)
    finally:
        if claimed:
            _INFLIGHT_TURNS.discard(lock_key)


__all__ = ["b66_ai_chat", "reset_dialogue_idempotency"]
