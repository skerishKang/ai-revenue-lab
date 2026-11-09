"""Same-origin browser routes for B62 orchestration presentation/approval intent."""

from __future__ import annotations

from .file_lane import file_resolver

import asyncio
import json
import logging
import math
import re
from collections.abc import Mapping
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from .auth_routes import auth_ready, current_user_id
from .b14_client import (
    PADIEM_IDENTITY_INSTRUCTION,
    ChatRuntimeError,
    _chat_product_identity_instruction,
)
from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .central_model_route_runtime import chat_request_tier_context
from .grounding import GroundingError, grounding_fallback_fields
from .history import HistoryForbidden, HistoryStore
from .history import PRODUCT_SCOPE_CHAT
from .calendar_product_rule import (
    PRODUCT_GOOGLE,
    PRODUCT_PADIEM,
    calendar_turn_product,
    native_calendar_turn_key,
)
from .native_calendar_adapter import NativeCalendarAdapterError
from .native_calendar_intent import try_native_calendar_chat
from .request_contract import declared_util_scope
from .member_grade_access import selected_admin_denial, selected_grade_denial
from .model_policy import (
    ResolvedModelPolicy,
    ModelPolicyError,
    resolve_model_policy,
    resolve_request_model_policy,
)
from .final_dispatch_guard_wiring import apply_guard_to_client, create_guard_from_request
from .model_first import (
    PATH_DIRECT,
    PATH_TOOL,
    execute_model_first_tool,
    model_first_context,
    model_first_enabled,
    model_supports_pc_tools,
    pc_context_is_relevant,
    pc_tools_for_context,
)
from .orchestration_bridge import (
    ENGINE_TIMEOUT_MESSAGE,
    B62EngineOrchestrationBridge,
    B62OrchestrationError,
)
from .orchestration_timing import OrchestrationTiming
from .orchestration_stream import (
    NDJSON_MEDIA_TYPE,
    ProgressFrameBuilder,
    line,
    ndjson_answer,
    stream_on_for,
    wants_ndjson,
)
from .public_chat import public_chat_result
from .request_contract import BrowserRequestError, _validate_payload_async
from .pc_correlation import run_hash
from .usage_gate import UsageGate

from .journal_host import ensure_journal_visible

_PC_TRACE_LOG = logging.getLogger("padiem_chat.pc_correlation")
_PC_TRACE_LOG.setLevel(logging.INFO)

MAX_ORCHESTRATION_BROWSER_BODY_BYTES = 256 * 1024
_CONTINUATION_RE = re.compile(r"^cont_[A-Za-z0-9_-]{8,123}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")

# 답변 시간 예산: the front door holds an answer request for at most 60s. Chat keeps a
# margin for the Engine's error projection and the return trip, so the browser
# gets the existing Korean timeout copy before Cloudflare's edge can answer.
ANSWER_BUDGET_HEADER = "x-padiem-answer-budget-ms"
DEFAULT_ANSWER_BUDGET_MS = 60_000.0
ANSWER_BUDGET_MARGIN_MS = 8_000.0
MIN_ANSWER_BUDGET_MS = 1_000.0


def _answer_budget_seconds(request: Request, timing: OrchestrationTiming) -> float:
    """Remaining answer budget after grounding/policy work, floored at 1s."""

    raw = request.headers.get(ANSWER_BUDGET_HEADER)
    try:
        budget_ms = float(raw) if raw is not None else DEFAULT_ANSWER_BUDGET_MS
    except (TypeError, ValueError):
        budget_ms = DEFAULT_ANSWER_BUDGET_MS
    if not math.isfinite(budget_ms) or budget_ms < MIN_ANSWER_BUDGET_MS:
        budget_ms = DEFAULT_ANSWER_BUDGET_MS
    # A caller may lower the window, never widen it past the front's ceiling.
    budget_ms = min(budget_ms, DEFAULT_ANSWER_BUDGET_MS)
    remaining_ms = budget_ms - timing.elapsed_ms() - ANSWER_BUDGET_MARGIN_MS
    return max(MIN_ANSWER_BUDGET_MS, remaining_ms) / 1000.0


def _error(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status_code)


def _bridge(request: Request) -> B62EngineOrchestrationBridge | None:
    bridge = getattr(request.app.state, "orchestration_bridge", None)
    return bridge if isinstance(bridge, B62EngineOrchestrationBridge) and bridge.ready else None


def _user_id(request: Request) -> str | None:
    if not auth_ready(request):
        return None
    return current_user_id(request)


def _stream_on_for(request: Request, uid: str | None) -> bool:
    """The per-request streaming decision from the startup-owned state."""
    return stream_on_for(
        getattr(request.app.state, "orchestration_stream_enabled", False),
        getattr(request.app.state, "orchestration_stream_users", frozenset()),
        uid,
        uid is None,
    )


async def orchestration_status(request: Request) -> JSONResponse:
    uid = _user_id(request)
    return JSONResponse(
        {
            "orchestration_ready": _bridge(request) is not None and uid is not None,
            "authenticated": uid is not None,
        },
        headers={"Cache-Control": "no-store"},
    )


async def _json_body(request: Request) -> Any:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_ORCHESTRATION_BROWSER_BODY_BYTES:
                raise B62OrchestrationError("request_too_large", "요청이 너무 큽니다.", status_code=413)
        except ValueError:
            raise B62OrchestrationError("invalid_request", "요청 형식이 올바르지 않습니다.", status_code=422) from None
    try:
        body = await read_bounded_request_body(
            request,
            max_bytes=MAX_ORCHESTRATION_BROWSER_BODY_BYTES,
        )
    except RequestBodyTooLarge:
        raise B62OrchestrationError(
            "request_too_large",
            "요청이 너무 큽니다.",
            status_code=413,
        ) from None
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise B62OrchestrationError("invalid_request", "요청 형식이 올바르지 않습니다.", status_code=422) from None


def parse_approval_intent(raw: Any) -> tuple[str, str, str]:
    if not isinstance(raw, dict) or set(raw) != {
        "continuationRef",
        "pauseId",
        "outcome",
        "requiresTrustedDecision",
    }:
        raise B62OrchestrationError("invalid_approval_intent", "확인 요청 형식이 올바르지 않습니다.", status_code=422)
    continuation_ref = raw.get("continuationRef")
    pause_id = raw.get("pauseId")
    outcome = raw.get("outcome")
    if not isinstance(continuation_ref, str) or not _CONTINUATION_RE.fullmatch(continuation_ref):
        raise B62OrchestrationError("invalid_approval_intent", "확인 요청 형식이 올바르지 않습니다.", status_code=422)
    if not isinstance(pause_id, str) or not _SAFE_ID_RE.fullmatch(pause_id):
        raise B62OrchestrationError("invalid_approval_intent", "확인 요청 형식이 올바르지 않습니다.", status_code=422)
    if outcome not in {"approved", "denied"} or raw.get("requiresTrustedDecision") is not True:
        raise B62OrchestrationError("invalid_approval_intent", "확인 선택이 올바르지 않습니다.", status_code=422)
    return continuation_ref, pause_id, outcome


def parse_cancel_intent(raw: Any) -> str:
    if not isinstance(raw, dict) or set(raw) != {"continuationRef"}:
        raise B62OrchestrationError("invalid_cancel_intent", "취소 요청 형식이 올바르지 않습니다.", status_code=422)
    ref = raw.get("continuationRef")
    if not isinstance(ref, str) or not _CONTINUATION_RE.fullmatch(ref):
        raise B62OrchestrationError("invalid_cancel_intent", "취소 요청 형식이 올바르지 않습니다.", status_code=422)
    return ref


def _latest_user(messages: list[dict[str, str]]) -> str:
    for item in reversed(messages):
        if item.get("role") == "user":
            return item["content"]
    raise B62OrchestrationError("invalid_request", "사용자 질문이 필요합니다.", status_code=422)


async def _save_terminal_history(
    request: Request,
    *,
    user_id: str,
    conversation_id: str | None,
    user_text: str,
    answer: str | None,
) -> str | None:
    if not answer:
        return conversation_id
    store: HistoryStore | None = request.app.state.history_store
    if store is None:
        return conversation_id
    try:
        return await store.append_exchange(user_id, conversation_id, user_text, answer, product_scope=PRODUCT_SCOPE_CHAT)
    except HistoryForbidden:
        return None
    except Exception:
        return conversation_id


async def _answer_native_calendar(
    request: Request,
    *,
    uid: str,
    raw: Any,
    messages: list[dict[str, str]],
    conversation_id: str | None,
    latest_user_text: str | None,
    timezone_name: str | None,
) -> JSONResponse:
    """Answer a PADIEM-calendar turn on this lane (#7273 후속).

    The same native adapter and the same turn key the stream route uses: one
    ask is answered by one product whichever route the composer picks.
    """

    calendar_store = getattr(request.app.state, "calendar_store", None)
    if calendar_store is None:
        return _error(
            "calendar_store_unavailable", "Calendar storage is unavailable", 503
        )
    client_turn_id = raw.get("calendar_turn_id") if isinstance(raw, dict) else None
    if not isinstance(client_turn_id, str):
        client_turn_id = request.headers.get("X-Padiem-Calendar-Turn-Id")
    if (
        not isinstance(client_turn_id, str)
        or not client_turn_id
        or len(client_turn_id) > 128
    ):
        client_turn_id = None
    turn_key = native_calendar_turn_key(
        uid=uid,
        conversation_id=conversation_id,
        message_count=len(messages),
        latest_user_text=latest_user_text,
        timezone_name=timezone_name,
        client_turn_id=client_turn_id,
    )
    try:
        native_result = await try_native_calendar_chat(
            request,
            calendar_store,
            uid,
            messages,
            timezone_name=timezone_name,
            turn_key=turn_key,
        )
    except NativeCalendarAdapterError as exc:
        return _error(exc.code, exc.message, exc.status_code)
    except Exception:  # noqa: BLE001 - the lane answers a bounded failure
        native_result = None
    if native_result is None:
        return _error("calendar_unavailable", "native calendar unavailable", 503)
    answer = str(native_result.get("answer", ""))
    saved_id = await _save_terminal_history(
        request,
        user_id=uid,
        conversation_id=conversation_id,
        user_text=latest_user_text or "",
        answer=answer,
    )
    body: dict[str, Any] = {"ok": True, "answer": answer}
    if saved_id is not None:
        body["conversation_id"] = saved_id
    return JSONResponse(body, headers={"Cache-Control": "no-store"})


def public_grounding_evidence(items: Any) -> list[dict[str, Any]]:
    """The browser-safe evidence projection for a grounded answer.

    The same allowlisted projection the Chat stream route uses: a title, a
    public URL, a snippet, the retrieval time and the source type. The
    provider identity stays server-side.
    """
    raw = [
        {
            "id": item.id,
            "title": item.title,
            "url": item.url,
            "snippet": item.snippet,
            "retrieved_at": item.retrieved_at,
            "provider": item.provider,
            "source_type": item.source_type,
        }
        for item in items
    ]
    projected = public_chat_result({"evidence": raw})
    evidence = projected.get("evidence", [])
    return evidence if isinstance(evidence, list) else []


async def api_orchestration(request: Request) -> JSONResponse:
    # #6732: 구간 시간만 남긴다. 실패·예외 경로에서도 그때까지 잠긴 구간을 남긴다.
    timing = OrchestrationTiming()
    response = None
    _turn_metrics(request)
    try:
        response = await _answer_orchestration(request, timing)
    except Exception:
        # #6812 계측: 예외로 끝난 턴도 한 줄 남긴다. 원문은 남기지 않는다.
        _emit_turn_summary(request, timing, "internal_error")
        raise
    finally:
        # NDJSON은 응답이 끝날 때 생성기가 직접 남긴다(engine_ms·save_ms 포함).
        if getattr(response, "media_type", None) != NDJSON_MEDIA_TYPE:
            timing.emit()
    if getattr(response, "media_type", None) == NDJSON_MEDIA_TYPE:
        _stream_turn_summary(request, response, timing)
    else:
        _emit_turn_summary(request, timing, _result_code(response))
    return response


def _turn_metrics(request: Request) -> dict[str, object]:
    """This turn's own counters, created once per request."""
    metrics = getattr(request.state, "orchestration_turn", None)
    if not isinstance(metrics, dict):
        metrics = {}
        request.state.orchestration_turn = metrics
    return metrics


def _conversation_hash(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


def _b14_input_chars(messages: list[dict[str, str]], context: str | None) -> int:
    """Characters this turn hands to B14: history text plus system context."""
    total = len(context or "")
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            total += len(content)
    return total


def _turn_summary_fields(request: Request) -> dict[str, object]:
    from .request_telemetry import stage_events

    metrics = dict(_turn_metrics(request))
    first_byte = next(
        (event.get("duration_ms") for event in stage_events()
         if event.get("stage") == "b14.stream.first_delta"),
        None,
    )
    metrics["first_byte_ms"] = first_byte if isinstance(first_byte, (int, float)) else None
    return metrics


def _emit_turn_summary(request: Request, timing: "OrchestrationTiming",
                      code: str | None) -> None:
    from .request_telemetry import emit_turn_summary

    try:
        duration_ms = timing.elapsed_ms()
    except Exception:
        duration_ms = 0.0
    emit_turn_summary(
        duration_ms=duration_ms, metrics=_turn_summary_fields(request), code=code,
    )


def _result_code(response: Any) -> str | None:
    status = getattr(response, "status_code", 200)
    return None if int(status) < 400 else "http_" + str(int(status))


def _stream_turn_summary(request: Request, response: Any, timing: "OrchestrationTiming") -> None:
    """Emit the one summary line when the stream actually ends."""
    original = response.body_iterator

    async def wrapped():
        code = None
        try:
            async for chunk in original:
                yield chunk
        except Exception:
            code = "stream_error"
            raise
        finally:
            _emit_turn_summary(request, timing, code)

    response.body_iterator = wrapped()


async def _answer_orchestration(request: Request, timing: OrchestrationTiming) -> JSONResponse:
    bridge = _bridge(request)
    if bridge is None:
        return _error("orchestration_unavailable", "작업 진행 상태 기능을 현재 사용할 수 없습니다.", 503)
    uid = _user_id(request)
    if uid is None:
        return _error("unauthorized", "이 기능을 사용하려면 로그인이 필요합니다.", 401)
    try:
        raw = await _json_body(request)
        # Assign the same canonical run before logging even for older clients
        # that do not supply one; the PC branch below reuses it for the Engine.
        trace_run_id = raw.get("pc_run_id") if isinstance(raw, dict) else None
        if isinstance(raw, dict) and trace_run_id is None:
            from .chat_pc_drive import _new_lane_run_id
            trace_run_id = _new_lane_run_id()
        trace_run = run_hash(trace_run_id)
        ensure_journal_visible(_PC_TRACE_LOG)
        _PC_TRACE_LOG.info("pc_chat stage=request_received run_hash=%s dispatch_id=none", trace_run or "none")
        # ``stream`` is a presentation choice, not a chat payload field. On the
        # model-first lane it is kept out of the browser contract validator while
        # the route still uses it to select the NDJSON response shape. With the
        # switch off the request stays byte-for-byte on the old contract.
        model_first_on = getattr(request.app.state, "model_first_enabled", False)
        validation_raw = (
            {key: value for key, value in raw.items() if key != "stream"}
            if model_first_on and isinstance(raw, dict) and "stream" in raw
            else raw
        )
        messages, skill, tool_request, attachments, conversation_id, project_id, custom = await _validate_payload_async(validation_raw, file_resolver=file_resolver(request))
        _PC_TRACE_LOG.info("pc_chat stage=contract_accepted run_hash=%s dispatch_id=none", trace_run or "none")
        timing.mark("validated")
        user_credential_ref = None
        if custom is not None:
            from .byok_bridge import resolve_reference
            from .byok_client import CustomProviderError
            from .byok_credentials import CustomProviderSelectionError
            try:
                resolved = await resolve_reference(request.app.state, uid, custom)
            except (CustomProviderError, CustomProviderSelectionError) as exc:
                return _error(getattr(exc, "code", "custom_provider_unsupported"), str(getattr(exc, "message", "사용자 키를 확인해 주세요.")), getattr(exc, "status_code", 422))
            if resolved is None:
                return _error("orchestration_not_applicable", "B14 경유 미지원 또는 비활성 상태이므로 기존 직행 경로를 사용합니다.", 409)
            byok_model, user_credential_ref = resolved
        if tool_request is not None or attachments or project_id is not None:
            return _error(
                "orchestration_not_applicable",
                "이 요청은 기존 채팅 경로에서 처리합니다.",
                409,
            )
        # #7273 후속: the representative decision — "캘린더·일정" is answered
        # by the PADIEM workspace calendar on THIS lane too; only an explicit
        # "구글 캘린더" names the external one. The same rule function the
        # stream route calls decides here, so the two surfaces cannot split.
        latest_turn_text = next(
            (item.get("content") for item in reversed(messages)
             if isinstance(item, Mapping) and item.get("role") == "user"),
            None,
        )
        # The connector READ tools are declared on the main chat turn. An
        # explicit Google name, or a broad drive read intent whose named
        # service is granted, falls back to /api/chat/stream here. The check
        # is bounded (3s, granted result cached 5min, one journal line);
        # grant-less or unverified owners keep this search path unchanged: the
        # check answers False without widening anything.
        if custom is None:
            from .chat_connector_tools import (
                connector_tools_granted_for_fallback,
                google_connector_broad_intent,
                google_connector_intent,
            )

            explicit_intent = google_connector_intent(latest_turn_text)
            broad_service = None if explicit_intent else google_connector_broad_intent(latest_turn_text)
            if broad_service == "calendar":
                # 대표 결정: 이름 없는 일정 질문은 PADIEM 캘린더가 답한다 —
                # the generic connector promotion no longer applies to it.
                broad_service = None
            if (explicit_intent or broad_service is not None) and await connector_tools_granted_for_fallback(
                request, uid=uid, service=broad_service,
            ):
                return _error(
                    "orchestration_not_applicable",
                    "이 요청은 커넥터 도구가 있는 기존 채팅 경로에서 처리합니다.",
                    409,
                )
        # #5015: an explicit browser tier is a preference, not authority.
        # Reuse the same server-side grade/administrator gates and resolver the
        # Chat stream route applies. A request without a tier resolves the
        # default product tier; slash-prefixed text stays ordinary prompt text.
        if custom is not None:
            policy = ResolvedModelPolicy(model_id=byok_model, messages=messages)
            product_identity = PADIEM_IDENTITY_INSTRUCTION
        elif "tier" in raw:
            if raw.get("tier") == "admin":
                admin_denial = await selected_admin_denial(request, uid)
                if admin_denial is not None:
                    return admin_denial
            else:
                tier_denial = await selected_grade_denial(request, uid, raw["tier"])
                if tier_denial is not None:
                    return tier_denial
            async with chat_request_tier_context(request, raw["tier"]):
                policy = resolve_request_model_policy(messages)
                # #5347: the Chat stream route composes the product identity while
                # the server-verified tier context is bound. The Engine lane has no
                # B14 product default, so the same render is sampled here and
                # carried on the Engine wire.
                product_identity = _chat_product_identity_instruction()
        else:
            policy = resolve_model_policy(messages)
            product_identity = PADIEM_IDENTITY_INSTRUCTION
    except BrowserRequestError as exc:
        return _error(exc.code, str(exc), 422)
    except ModelPolicyError as exc:
        return _error(exc.code, exc.message, 422)
    except B62OrchestrationError as exc:
        return _error(exc.code, exc.user_message, exc.status_code)

    timing.mark("policy")
    store: HistoryStore | None = request.app.state.history_store
    if conversation_id is not None and store is not None:
        try:
            existing = await store.get_conversation(uid, conversation_id, product_scope=PRODUCT_SCOPE_CHAT)
        except Exception:
            return _error("history_unavailable", "대화 기록을 현재 사용할 수 없습니다.", 503)
        if existing is None:
            return _error("conversation_not_found", "대화를 찾을 수 없습니다.", 404)
    timing.mark("conversation")

    if getattr(request.app.state, "usage_gate_enforced", False):
        usage_gate: UsageGate = request.app.state.usage_gate
        decision = await usage_gate.authorize(
            raw_ip=request.headers.get("cf-connecting-ip"),
            user_id=uid,
        )
        if not decision.allowed:
            headers = {"Retry-After": str(decision.retry_after_seconds)} if decision.retry_after_seconds is not None else None
            return JSONResponse(
                {"error": {"code": decision.code, "message": decision.user_message}},
                status_code=decision.status_code,
                headers=headers,
            )

    timing.mark("usage")
    user_text = _latest_user(messages)
    # #7273 후속: the representative decision — "캘린더·일정" is answered by
    # the PADIEM workspace calendar on THIS lane too; only an explicit
    # "구글 캘린더" names the external one. The same rule function the stream
    # route calls decides here, so the two surfaces cannot split. This runs
    # after the conversation check and the usage gate, exactly the order the
    # stream route answers a native-calendar turn in.
    timezone_name = (
        raw.get("timezone")
        if isinstance(raw, dict) and isinstance(raw.get("timezone"), str)
        else None
    )
    calendar_product = (
        None
        if custom is not None or declared_util_scope(raw) is not None
        else calendar_turn_product(user_text, timezone_name=timezone_name)
    )
    if calendar_product == PRODUCT_PADIEM:
        return await _answer_native_calendar(
            request,
            uid=uid,
            raw=raw,
            messages=messages,
            conversation_id=conversation_id,
            latest_user_text=user_text,
            timezone_name=timezone_name,
        )
    if calendar_product == PRODUCT_GOOGLE:
        from .chat_connector_tools import (
            GOOGLE_CALENDAR_CONNECT_NOTE,
            calendar_read_reachable,
        )

        if await calendar_read_reachable(request, uid=uid):
            return _error(
                "orchestration_not_applicable",
                "이 요청은 커넥터 도구가 있는 기존 채팅 경로에서 처리합니다.",
                409,
            )
        answer = GOOGLE_CALENDAR_CONNECT_NOTE
        saved_id = await _save_terminal_history(
            request,
            user_id=uid,
            conversation_id=conversation_id,
            user_text=user_text,
            answer=answer,
        )
        body: dict[str, Any] = {"ok": True, "answer": answer}
        if saved_id is not None:
            body["conversation_id"] = saved_id
        return JSONResponse(body, headers={"Cache-Control": "no-store"})
    # The server verification chooses only whether PC tools may be offered.
    # Model interpretation stays inside the same Engine turn.
    from .chat_pc_drive import resolve_chat_pc_stream_context
    pc_context = await resolve_chat_pc_stream_context(
        request, uid=uid, requested_device_id=raw.get("device_id"),
        user_text=user_text,
    )
    timing.mark("pc_context")
    # #4469: in production the PADIEM Chat composer is answered by THIS lane
    # (the browser tries the orchestration route first), so the shared public
    # web search has to run here as well. The existing Core search decision,
    # the existing TinyFish/Daum provider and the existing evidence
    # projection are reused unchanged: only the lane that actually answers the
    # turn now runs the retrieval. A request that needs no current external
    # fact still performs no provider call.
    auto_grounding = getattr(request.app.state, "auto_grounding", None)
    prepare_grounding = getattr(auto_grounding, "prepare", None)
    grounding_context: str | None = None
    grounded_evidence: list[dict[str, Any]] = []
    grounding_notice: dict[str, Any] = {}
    auto_plan = None
    if callable(prepare_grounding):
        try:
            _explicit = bool(raw.get("web_search")) if isinstance(raw, dict) else False
            try:
                auto_plan = await prepare_grounding(
                    messages,
                    skill=skill,
                    additional_system_context=None,
                    explicit_search=_explicit,
                )
            except TypeError:
                auto_plan = await prepare_grounding(
                    messages,
                    skill=skill,
                    additional_system_context=None,
                )
        except GroundingError as exc:
            grounding_notice = grounding_fallback_fields(exc)
        if getattr(auto_plan, "error", None) is not None:
            grounding_notice = grounding_fallback_fields(auto_plan.error)
        prepared = getattr(auto_plan, "prepared", None)
        if prepared is not None:
            grounding_context = prepared.context
            grounded_evidence = public_grounding_evidence(prepared.evidence)

    timing.mark("grounding")
    # #6812 계측: 이 턴이 무엇을 얼마나 B14로 보냈는지 한 줄로 남긴다. 새 상한도,
    # 새 차단도 없다 — 숫자만 기록한다.
    _turn_metrics(request).update({
        "tier": str(raw.get("tier") or "free") if isinstance(raw, dict) else "free",
        "conversation": _conversation_hash(conversation_id),
        "web_search": bool(grounded_evidence),
        "evidence_count": len(grounded_evidence),
        "evidence_chars": sum(
            len(str(item.get("snippet") or "")) for item in grounded_evidence
        ),
        "history_turns": len(messages),
        "input_chars": _b14_input_chars(messages, grounding_context),
    })
    # #7165: this lane (the browser tries it first) must carry the same
    # tool-presence sentence the plain Chat lane does. Without it a PC-capable
    # turn still answered "PADIEM is a remote AI, it cannot reach the PC".
    from .chat_routes import join_system_context, pc_note_applies, pc_turn_note

    pc_offer = pc_context.get("pc_tools") if isinstance(pc_context, Mapping) else None
    answer_context = join_system_context(
        grounding_context,
        pc_turn_note(pc_offer) if pc_note_applies(user_text, pc_offer) else "",
    )
    if model_first_on and user_credential_ref is None:
        model_first_response = await _answer_model_first(
            request,
            timing=timing,
            uid=uid,
            raw=raw,
            messages=messages,
            skill=skill,
            policy=policy,
            pc_context=pc_context,
            grounding_context=grounding_context,
            grounding_notice=grounding_notice,
            grounded_evidence=grounded_evidence,
            conversation_id=conversation_id,
            user_text=user_text,
            store=store,
            wants_stream=(
                _stream_on_for(request, uid)
                and wants_ndjson(raw, request.headers.get("accept"))
            ),
        )
        if model_first_response is not None:
            return model_first_response
    if pc_context is not None or user_credential_ref is not None:
        if pc_context is None:
            # A text-only BYOK turn stages message history, never a PC run.
            pc_context = {"workspace_id": "personal", "subject_id": None, "pc_tools": None}
        from .chat_pc_drive import ChatPCDriveError, _client_lane_run_id, pc_scope_notice_for_run
        from .claw_live_events import chat_pc_orchestration_sse
        begin = getattr(store, "begin_chat_stream_turn", None)
        finish = getattr(store, "finish_chat_stream_turn", None)
        if not callable(begin) or not callable(finish):
            return _error("history_unavailable", "대화 기록을 현재 사용할 수 없습니다.", 503)
        stream_messages = policy.messages
        if conversation_id is not None:
            from .chat_routes import _restore_owner_chat_model_messages
            try:
                stream_messages = await _restore_owner_chat_model_messages(
                    store, uid, conversation_id, existing, list(policy.messages),
                )
            except OverflowError:
                return _error("history_context_too_large", "대화 맥락이 전송 한도를 초과했습니다.", 413)
            except Exception:
                return _error("history_context_incomplete", "대화 맥락을 현재 복원할 수 없습니다.", 503)
        try:
            pc_run_id = _client_lane_run_id(raw.get("pc_run_id")) or trace_run_id
            saved_id = await begin(
                user_id=uid, run_id=pc_run_id, workspace_id=pc_context["workspace_id"],
                user_text=user_text, conversation_id=conversation_id,
            )
        except HistoryForbidden:
            return _error("chat_pc_run_id_conflict", "이미 사용한 PC 작업 실행 ID입니다.", 409)
        except ChatPCDriveError as exc:
            return _error(exc.code, exc.user_message, exc.status_code)
        except Exception as exc:
            error = ChatPCDriveError("chat_pc_store_unavailable", "대화 기록을 현재 사용할 수 없습니다.")
            error.__cause__ = exc
            return JSONResponse({"error": error.public_error()}, status_code=503)
        from .pc_action_context import build_pc_action_context
        action_context = build_pc_action_context(
            stream_messages, user_text=user_text,
            trusted_history=conversation_id is not None,
            tool_results=(("web", grounding_context),),
        ) if pc_context["pc_tools"] is not None else None
        from .pc_delegation_routes import load_pc_delegation

        pc_delegation = (await load_pc_delegation(request, uid)
                         if pc_context["pc_tools"] is not None else None)
        stream = bridge.start_stream(
            user_id=uid, messages=stream_messages, skill=skill, model_id=policy.model_id,
            user_text=user_text, conversation_id=saved_id,
            pc_tools=pc_context["pc_tools"], subject_id=pc_context["subject_id"],
            session_id=pc_run_id, additional_system_context=answer_context,
            product_identity=product_identity,
            **({"pc_action_context": action_context} if action_context is not None else {}),
            **({"pc_delegation": pc_delegation} if pc_delegation is not None else {}),
            **({"user_credential_ref": user_credential_ref,
                "byok_selection": {"provider": custom.provider, "model": custom.model}}
               if user_credential_ref is not None else {}),
        )
        async def scope_notice():
            return await pc_scope_notice_for_run(request, run_id=pc_run_id)
        async def fail_stream():
            # A terminal Engine/contract error is evidence of failure; a browser
            # disconnect is not. The existing owner-scoped guard preserves a
            # verified completion and creates no row for an ordinary text turn.
            await store.update_claw_run_status(uid, pc_run_id, "failed")
        async def complete_stream(result):
            fields = {"conversation_id": saved_id}
            try:
                await finish(user_id=uid, run_id=pc_run_id, answer=result.answer)
            except Exception:
                # Match normal history-save behavior: a verified answer remains
                # visible even if optional history projection is unavailable.
                pass
            notice = await scope_notice()
            if notice is not None:
                fields["scope_notice"] = notice
            return fields
        completion_fields = dict(grounding_notice)
        if grounded_evidence:
            completion_fields.update(answer_status="answered_with_evidence",
                evidence=grounded_evidence, tool={"id": "web_search", "title": "웹 검색"})
        return chat_pc_orchestration_sse(
            stream, pc_run_id=pc_run_id, on_completed=complete_stream,
            on_scope=scope_notice, done_fields=completion_fields, on_failed=fail_stream,
            pending_fields={"run_id": pc_run_id, "conversation_id": saved_id},
        )

    answer_budget_seconds = _answer_budget_seconds(request, timing)
    if _stream_on_for(request, uid) and wants_ndjson(
        raw, request.headers.get("accept")
    ):
        # #6742: 일반 답변도 엔진 토큰이 오는 대로 흘려보낸다. 게이트·등급·PC 순서는 그대로다.
        base_kwargs = dict(
            user_id=uid, messages=policy.messages, skill=skill, model_id=policy.model_id,
            user_text=user_text, conversation_id=conversation_id,
            additional_system_context=answer_context, product_identity=product_identity,
            timeout_seconds=answer_budget_seconds,
        )

        async def completed_stream(result):
            saved = await _save_terminal_history(
                request, user_id=uid, conversation_id=result.conversation_id,
                user_text=result.user_text, answer=result.answer,
            )
            fields = {
                "conversation_id": saved or result.conversation_id,
                "message_id": saved or result.conversation_id,
                "usage": None,
            }
            fields.update(grounding_notice)
            if grounded_evidence:
                fields.update(answer_status="answered_with_evidence",
                              evidence=grounded_evidence, tool={"id": "web_search", "title": "웹 검색"})
            return fields

        return StreamingResponse(
            ndjson_answer(
                bridge=bridge,
                stream_kwargs={**base_kwargs, "pc_tools": None, "subject_id": None, "session_id": None},
                buffered_kwargs=base_kwargs,
                timing=timing,
                on_completed=completed_stream,
                timeout_seconds=answer_budget_seconds,
            ),
            media_type=NDJSON_MEDIA_TYPE,
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    try:
        result = await asyncio.wait_for(
            bridge.start(
                user_id=uid,
                messages=policy.messages,
                skill=skill,
                model_id=policy.model_id,
                user_text=user_text,
                conversation_id=conversation_id,
                additional_system_context=answer_context,
                product_identity=product_identity,
                timeout_seconds=answer_budget_seconds,
            ),
            timeout=answer_budget_seconds,
        )
    except asyncio.TimeoutError:
        return _error("upstream_timeout", ENGINE_TIMEOUT_MESSAGE, 504)
    except B62OrchestrationError as exc:
        return _error(exc.code, exc.user_message, exc.status_code)

    timing.mark("engine")
    saved_id = await _save_terminal_history(
        request,
        user_id=uid,
        conversation_id=result.conversation_id,
        user_text=result.user_text,
        answer=result.answer,
    )
    timing.mark("save")
    payload: dict[str, Any] = {
        "orchestration": dict(result.orchestration),
        "answer": result.answer,
        "decision_status": result.decision_status,
    }
    payload.update(grounding_notice)
    if grounded_evidence:
        # The browser contract for a grounded answer: the same tool marker and
        # the same public evidence the Chat stream route already returns.
        payload["answer_status"] = "answered_with_evidence"
        payload["evidence"] = grounded_evidence
        payload["tool"] = {"id": "web_search", "title": "웹 검색"}
    if saved_id is not None:
        payload["conversation_id"] = saved_id
    return JSONResponse(payload)


def _model_first_payload(
    answer: str,
    saved_id: str | None,
    grounding_notice: dict[str, Any],
    grounded_evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "orchestration": {
            "events": [],
            "approval_pause": None,
            "continuation_ref": None,
            "answer": answer,
        },
        "answer": answer,
        "decision_status": None,
    }
    payload.update(grounding_notice)
    if grounded_evidence:
        payload.update(
            answer_status="answered_with_evidence",
            evidence=grounded_evidence,
            tool={"id": "web_search", "title": "웹 검색"},
        )
    if saved_id is not None:
        payload["conversation_id"] = saved_id
    return payload


def _model_first_done_fields(
    saved_id: str | None,
    grounding_notice: dict[str, Any],
    grounded_evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    fields: dict[str, Any] = dict(grounding_notice)
    if grounded_evidence:
        fields.update(
            answer_status="answered_with_evidence",
            evidence=grounded_evidence,
            tool={"id": "web_search", "title": "웹 검색"},
        )
    fields["usage"] = None
    if saved_id is not None:
        fields["conversation_id"] = saved_id
        fields["message_id"] = saved_id
    return fields


def _model_first_error_response(exc: BaseException):
    from .chat_pc_drive import ChatPCDriveError

    if isinstance(exc, (ChatRuntimeError, ChatPCDriveError)):
        code = exc.code if isinstance(exc.code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", exc.code) else "model_first_failed"
        status = exc.status_code if isinstance(exc.status_code, int) else 502
        return _error(code, exc.user_message, status)
    return _error(
        "model_first_failed",
        "답변을 불러오지 못했습니다. 다시 시도해 주세요.",
        502,
    )


def _model_first_error_code(exc: BaseException) -> str:
    from .chat_pc_drive import ChatPCDriveError

    if isinstance(exc, (ChatRuntimeError, ChatPCDriveError)):
        code = exc.code
        if isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code):
            return code
    return "model_first_failed"


async def _close_model_first_stream(stream: Any) -> None:
    closer = getattr(stream, "aclose", None)
    if not callable(closer):
        return
    try:
        await closer()
    except Exception:
        pass


async def _first_model_first_event(stream: Any):
    async for event in stream:
        if getattr(event, "tool_call", None) is not None:
            return event
        if getattr(event, "delta_thought", None):
            return event
        if getattr(event, "delta_content", None):
            return event
        if getattr(event, "done", False):
            return event
    return None


async def _model_first_open_stream(
    request: Request,
    *,
    raw: dict[str, Any],
    messages: list[dict[str, str]],
    skill: Any,
    policy: ResolvedModelPolicy,
    context: str | None,
    tools: tuple[Any, ...],
):
    guard = await create_guard_from_request(
        request,
        policy.model_id,
        getattr(request.app.state, "central_model_policy_store", None),
        getattr(request.app.state, "b14_catalog_source", None),
    )
    client = apply_guard_to_client(request.app.state.b14_client, guard)
    if tools:
        return client.stream_text_auto(
            messages,
            skill=skill,
            additional_system_context=context,
            tools=tools,
            tool_choice="auto",
        )
    return client.stream_text_auto(
        messages, skill=skill, additional_system_context=context
    )


async def _answer_model_first(
    request: Request,
    *,
    timing: OrchestrationTiming,
    uid: str,
    raw: dict[str, Any],
    messages: list[dict[str, str]],
    skill: Any,
    policy: ResolvedModelPolicy,
    pc_context: dict[str, Any] | None,
    grounding_context: str | None,
    grounding_notice: dict[str, Any],
    grounded_evidence: list[dict[str, Any]],
    conversation_id: str | None,
    user_text: str,
    store: HistoryStore | None,
    wants_stream: bool,
):
    if pc_context is not None:
        if not model_supports_pc_tools(policy.model_id):
            return None
        from .chat_pc_drive import chat_pc_route_declares_tools

        if not await chat_pc_route_declares_tools(request, policy.model_id):
            return None
    if getattr(request.app.state, "b14_client", None) is None:
        return None
    tools = pc_tools_for_context(pc_context, user_text)
    context = grounding_context
    if pc_context is not None or pc_context_is_relevant(
        user_text, requested_device=bool(raw.get("device_id"))
    ):
        context = await model_first_context(
            request, owner_id=uid, grounding_context=grounding_context
        )
    # #7165: the sentence follows the tool tuple this dispatch actually carries.
    from .chat_routes import join_system_context, pc_note_applies, pc_turn_note

    context = join_system_context(
        context,
        pc_turn_note(tools) if pc_note_applies(user_text, tools) else "",
    )
    common = dict(
        timing=timing,
        raw=raw,
        messages=messages,
        skill=skill,
        policy=policy,
        context=context,
        tools=tools,
        uid=uid,
        user_text=user_text,
        conversation_id=conversation_id,
        store=store,
        grounding_notice=grounding_notice,
        grounded_evidence=grounded_evidence,
        grounding_context=grounding_context,
    )
    if wants_stream:
        timing.set_path(PATH_DIRECT)
        return StreamingResponse(
            _model_first_ndjson(request, **common),
            media_type=NDJSON_MEDIA_TYPE,
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )
    return await _model_first_json(request, **common)


async def _model_first_json(
    request: Request,
    *,
    timing: OrchestrationTiming,
    raw: dict[str, Any],
    messages: list[dict[str, str]],
    skill: Any,
    policy: ResolvedModelPolicy,
    context: str | None,
    tools: tuple[Any, ...],
    uid: str,
    user_text: str,
    conversation_id: str | None,
    store: HistoryStore | None,
    grounding_notice: dict[str, Any],
    grounded_evidence: list[dict[str, Any]],
    grounding_context: str | None,
):
    tool_call = None
    parts: list[str] = []
    try:
        async with chat_request_tier_context(request, raw.get("tier", "free")):
            stream = await _model_first_open_stream(
                request,
                raw=raw,
                messages=messages,
                skill=skill,
                policy=policy,
                context=context,
                tools=tools,
            )
            try:
                first = await _first_model_first_event(stream)
                if first is None or (
                    first.delta_content is None
                    and getattr(first, "delta_thought", None) is None
                    and first.tool_call is None
                ):
                    return _error(
                        "model_first_empty",
                        "AI가 표시할 답변을 만들지 못했습니다.",
                        502,
                    )
                if first.tool_call is not None:
                    tool_call = first.tool_call
                else:
                    if getattr(first, "delta_thought", None):
                        # A thinking summary is the first visible byte; it is
                        # presentation-only and stays out of `parts`.
                        timing.mark("first_token")
                    if first.delta_content is not None:
                        parts.append(first.delta_content)
                        timing.mark("first_token")
                    async for event in stream:
                        if event.delta_content:
                            parts.append(event.delta_content)
                        if event.done:
                            break
            finally:
                await _close_model_first_stream(stream)
    except Exception as exc:
        return _model_first_error_response(exc)

    if tool_call is not None:
        offered = {tool.name for tool in tools}
        if tool_call.name not in offered:
            return _error(
                "model_first_tool_not_allowed",
                "요청한 도구를 실행할 수 없습니다.",
                403,
            )
        timing.set_path(PATH_TOOL)
        try:
            outcome = await execute_model_first_tool(
                request,
                tool_name=tool_call.name,
                policy=policy,
                messages=messages,
                skill=skill,
                raw=raw,
                user_text=user_text,
                conversation_id=conversation_id,
                store=store,
                grounding_context=grounding_context,
            )
        except Exception as exc:
            return _model_first_error_response(exc)
        if outcome is None:
            return _error(
                "model_first_tool_unavailable",
                "PC 작업을 시작하지 못했습니다. 다시 시도해 주세요.",
                502,
            )
        answer, saved_id = outcome
        timing.mark("engine")
        timing.mark("save")
        return JSONResponse(
            _model_first_payload(
                answer, saved_id, grounding_notice, grounded_evidence
            )
        )

    timing.set_path(PATH_DIRECT)
    answer = "".join(parts).strip()
    if not answer:
        return _error(
            "model_first_empty", "AI가 표시할 답변을 만들지 못했습니다.", 502
        )
    timing.mark("engine")
    saved_id = await _save_terminal_history(
        request,
        user_id=uid,
        conversation_id=conversation_id,
        user_text=user_text,
        answer=answer,
    )
    timing.mark("save")
    return JSONResponse(
        _model_first_payload(answer, saved_id, grounding_notice, grounded_evidence)
    )


async def _model_first_ndjson(
    request: Request,
    *,
    timing: OrchestrationTiming,
    raw: dict[str, Any],
    messages: list[dict[str, str]],
    skill: Any,
    policy: ResolvedModelPolicy,
    context: str | None,
    tools: tuple[Any, ...],
    uid: str,
    user_text: str,
    conversation_id: str | None,
    store: HistoryStore | None,
    grounding_notice: dict[str, Any],
    grounded_evidence: list[dict[str, Any]],
    grounding_context: str | None,
):
    tool_call = None
    parts: list[str] = []
    try:
        yield line({"type": "meta", "stream": True})
        async with chat_request_tier_context(request, raw.get("tier", "free")):
            stream = await _model_first_open_stream(
                request,
                raw=raw,
                messages=messages,
                skill=skill,
                policy=policy,
                context=context,
                tools=tools,
            )
            try:
                first = await _first_model_first_event(stream)
                if first is None or (
                    first.delta_content is None
                    and getattr(first, "delta_thought", None) is None
                    and first.tool_call is None
                ):
                    yield line({"type": "error", "code": "model_first_empty"})
                    return
                if first.tool_call is not None:
                    if getattr(first, "delta_thought", None):
                        timing.mark("first_token")
                        yield line({"type": "thought", "text": getattr(first, "delta_thought", None)})
                    tool_call = first.tool_call
                else:
                    if getattr(first, "delta_thought", None):
                        timing.mark("first_token")
                        yield line({"type": "thought", "text": getattr(first, "delta_thought", None)})
                    if first.delta_content is not None:
                        timing.mark("first_token")
                        parts.append(first.delta_content)
                        yield line({"type": "delta", "text": first.delta_content})
                    async for event in stream:
                        candidate_tool_call = getattr(event, "tool_call", None)
                        if candidate_tool_call is not None:
                            if getattr(event, "delta_thought", None):
                                yield line({"type": "thought", "text": getattr(event, "delta_thought", None)})
                            tool_call = candidate_tool_call
                            break
                        if getattr(event, "delta_thought", None):
                            yield line({"type": "thought", "text": getattr(event, "delta_thought", None)})
                        if event.delta_content:
                            parts.append(event.delta_content)
                            yield line({"type": "delta", "text": event.delta_content})
                        if event.done:
                            break
            finally:
                await _close_model_first_stream(stream)

        if tool_call is not None:
            if tool_call.name not in {tool.name for tool in tools}:
                yield line(
                    {"type": "error", "code": "model_first_tool_not_allowed"}
                )
                return
            timing.set_path(PATH_TOOL)
            progress = ProgressFrameBuilder()
            started = progress.frame("tool_started", tool_name=tool_call.name)
            if started is not None:
                yield line(started)
            try:
                outcome = await execute_model_first_tool(
                    request,
                    tool_name=tool_call.name,
                    policy=policy,
                    messages=messages,
                    skill=skill,
                    raw=raw,
                    user_text=user_text,
                    conversation_id=conversation_id,
                    store=store,
                    grounding_context=grounding_context,
                )
            except Exception as exc:
                failed = progress.frame("tool_failed", tool_name=tool_call.name)
                if failed is not None:
                    yield line(failed)
                yield line(
                    {"type": "error", "code": _model_first_error_code(exc)}
                )
                return
            if outcome is None:
                failed = progress.frame("tool_failed", tool_name=tool_call.name)
                if failed is not None:
                    yield line(failed)
                yield line(
                    {"type": "error", "code": "model_first_tool_unavailable"}
                )
                return
            answer, saved_id = outcome
            timing.mark("engine")
            timing.mark("save")
            completed = progress.frame("tool_completed", tool_name=tool_call.name)
            if completed is not None:
                yield line(completed)
            yield line({"type": "delta", "text": answer})
            yield line(
                {
                    "type": "done",
                    "done": True,
                    **_model_first_done_fields(
                        saved_id, grounding_notice, grounded_evidence
                    ),
                }
            )
            return

        timing.set_path(PATH_DIRECT)
        answer = "".join(parts).strip()
        if not answer:
            yield line({"type": "error", "code": "model_first_empty"})
            return
        timing.mark("engine")
        saved_id = await _save_terminal_history(
            request,
            user_id=uid,
            conversation_id=conversation_id,
            user_text=user_text,
            answer=answer,
        )
        timing.mark("save")
        yield line(
            {
                "type": "done",
                "done": True,
                **_model_first_done_fields(
                    saved_id, grounding_notice, grounded_evidence
                ),
            }
        )
    except Exception as exc:
        yield line({"type": "error", "code": _model_first_error_code(exc)})
    finally:
        timing.emit()


def _resume_skill():
    try:
        from .task_modes import get_task_mode

        return get_task_mode("auto")
    except Exception:
        from types import SimpleNamespace

        return SimpleNamespace(id="auto")

async def api_orchestration_resume(request: Request) -> JSONResponse:
    bridge = _bridge(request)
    if bridge is None:
        return _error("orchestration_unavailable", "작업 진행 상태 기능을 현재 사용할 수 없습니다.", 503)
    uid = _user_id(request)
    if uid is None:
        return _error("unauthorized", "이 기능을 사용하려면 로그인이 필요합니다.", 401)
    try:
        raw = await _json_body(request)
        continuation_ref, pause_id, outcome = parse_approval_intent(raw)
        async def user_credential_resolver(selection):
            from .byok_bridge import resolve_reference
            from .byok_client import CustomProviderError
            from .byok_credentials import CustomProviderSelectionError
            from .request_contract import parse_custom_selection
            try:
                return await resolve_reference(request.app.state, uid, parse_custom_selection(selection))
            except (CustomProviderError, CustomProviderSelectionError, BrowserRequestError):
                raise B62OrchestrationError("byok_credential_required", "사용자 키를 다시 확인해 주세요.", status_code=409) from None
        result = await bridge.resume(
            user_id=uid,
            continuation_ref=continuation_ref,
            pause_id=pause_id,
            outcome=outcome,
            user_credential_resolver=user_credential_resolver,
        )
    except B62OrchestrationError as exc:
        return _error(exc.code, exc.user_message, exc.status_code)

    # #4469: resume must keep the same public evidence contract as the
    # original grounded turn, so the sources survive an approval continuation.
    grounded_evidence: list[dict[str, Any]] = []
    auto_grounding = getattr(request.app.state, "auto_grounding", None)
    prepare_grounding = getattr(auto_grounding, "prepare", None)
    if callable(prepare_grounding) and isinstance(result.user_text, str) and result.user_text.strip():
        try:
            try:
                auto_plan = await prepare_grounding(
                    [{"role": "user", "content": result.user_text}],
                    skill=_resume_skill(),
                    additional_system_context=None,
                    explicit_search=False,
                )
            except TypeError:
                auto_plan = await prepare_grounding(
                    [{"role": "user", "content": result.user_text}],
                    skill=_resume_skill(),
                    additional_system_context=None,
                )
        except GroundingError:
            auto_plan = None
        prepared = getattr(auto_plan, "prepared", None) if auto_plan is not None else None
        if prepared is not None:
            grounded_evidence = public_grounding_evidence(prepared.evidence)

    stream_run_id = getattr(result, "stream_run_id", None)
    if stream_run_id is not None:
        # The first stream already persisted its user turn before pausing.
        # Resume appends only the answer, under the same owner/run receipt.
        saved_id = result.conversation_id
        finish = getattr(getattr(request.app.state, "history_store", None), "finish_chat_stream_turn", None)
        if isinstance(result.answer, str) and result.answer and callable(finish):
            try:
                saved_id = await finish(user_id=uid, run_id=stream_run_id, answer=result.answer)
            except Exception:
                pass
    else:
        saved_id = await _save_terminal_history(
            request, user_id=uid, conversation_id=result.conversation_id,
            user_text=result.user_text, answer=result.answer,
        )
    payload: dict[str, Any] = {
        "orchestration": dict(result.orchestration),
        "answer": result.answer,
        "decision_status": result.decision_status,
    }
    if grounded_evidence:
        payload["answer_status"] = "answered_with_evidence"
        payload["evidence"] = grounded_evidence
        payload["tool"] = {"id": "web_search", "title": "웹 검색"}
    if saved_id is not None:
        payload["conversation_id"] = saved_id
    return JSONResponse(payload)


async def api_orchestration_cancel(request: Request) -> JSONResponse:
    bridge = _bridge(request)
    if bridge is None:
        return _error("orchestration_unavailable", "작업 진행 상태 기능을 현재 사용할 수 없습니다.", 503)
    uid = _user_id(request)
    if uid is None:
        return _error("unauthorized", "이 기능을 사용하려면 로그인이 필요합니다.", 401)
    try:
        raw = await _json_body(request)
        continuation_ref = parse_cancel_intent(raw)
        result = await bridge.cancel(user_id=uid, continuation_ref=continuation_ref)
    except B62OrchestrationError as exc:
        return _error(exc.code, exc.user_message, exc.status_code)
    return JSONResponse(
        {
            "orchestration": dict(result.orchestration),
            "answer": None,
            "decision_status": "cancelled",
        }
    )


def install_orchestration_routes(
    app: Any,
    bridge: B62EngineOrchestrationBridge | None,
    *,
    stream_enabled: bool = False,
    stream_users: frozenset[str] | None = None,
    model_first_enabled: bool = False,
) -> None:
    """Install routes ahead of the catch-all static Mount without changing app_factory."""
    app.state.orchestration_bridge = bridge
    app.state.orchestration_stream_enabled = stream_enabled
    app.state.orchestration_stream_users = frozenset(stream_users or ())
    app.state.model_first_enabled = model_first_enabled
    routes = [
        Route("/api/orchestration/status", orchestration_status, methods=["GET"]),
        Route("/api/orchestration", api_orchestration, methods=["POST"]),
        Route("/api/orchestration/resume", api_orchestration_resume, methods=["POST"]),
        Route("/api/orchestration/cancel", api_orchestration_cancel, methods=["POST"]),
    ]
    for route in reversed(routes):
        app.router.routes.insert(0, route)
