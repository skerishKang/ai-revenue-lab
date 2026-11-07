from __future__ import annotations

from .file_lane import file_resolver

import asyncio
import base64
import json
from collections.abc import Mapping
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

from .attachments import ImageAttachment
from .binary_attachment_frame import decode_binary_attachment_frame
from .auth_routes import auth_ready, current_user_id
from .drive_general_grounding import DriveGroundingError, drive_general_grounding
from .auto_grounding import (
    AutoGroundingService,
    auto_grounding_may_continue,
    auto_grounding_skip_fields,
)
from .native_calendar_intent import parse_native_calendar_intent, try_native_calendar_chat
from .native_calendar_adapter import NativeCalendarAdapterError
from .chat_connector_tools import (
    google_connector_intent,
    google_connector_turn_for_text,
    is_connector_tool_name,
)
from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .b14_client import B14Client, ChatRuntimeError
from .byok_client import CustomProviderError, complete_owner_custom
from .byok_credentials import CustomProviderSelectionError
from .chat_stream_timing import ChatStreamTiming
from .config import Settings
from .conversation_routes import _history_unavailable
from .documents import (
    DocumentAttachment,
    build_documents_context,
    build_project_files_context,
    combine_reference_context,
)
from .grounding import GroundedChatService, GroundingError, grounding_fallback_fields
from .history import (
    HISTORY_PREVIEW_SUFFIX,
    MAX_HISTORY_MESSAGE_CHARS,
    MAX_MODEL_CONTEXT_BYTES,
    HistoryContextIncomplete,
    HistoryForbidden,
    HistoryStore,
    build_project_context,
)
from .history import PRODUCT_SCOPE_CHAT
from .model_policy import model_supports, request_tier_context, resolve_request_model_policy, FREE_B14_MODEL_ID, FREE_FALLBACK_B14_MODEL_ID
from .central_model_route_runtime import chat_request_tier_context
from .final_dispatch_guard_wiring import apply_guard_to_client, create_guard_from_request
from .member_grade_access import selected_admin_denial, selected_grade_denial
from .tier_identity_client import is_padiem_identity_question
from .project_files import ProjectFileStore
from .public_chat import public_chat_result
from .request_contract import (
    MAX_BROWSER_BODY_BYTES,
    BrowserRequestError,
    CustomModelSelection,
    _apply_b62_model_policy,
    _validate_payload_async,
    declared_util_scope,
)
from .request_telemetry import emit_stage_event
from .tool_presentations import get_tool_presentation
from .usage_gate import UsageGate
from .web_tools import WebToolError


def _public_evidence(items) -> list[dict[str, Any]]:
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


def _too_large_response() -> JSONResponse:
    return JSONResponse({"error": {"code": "request_too_large", "message": "요청이 너무 큽니다."}}, status_code=413)


def _project_files_unavailable() -> JSONResponse:
    return JSONResponse({"error": {"code": "project_files_unavailable", "message": "프로젝트 파일을 현재 사용할 수 없습니다."}}, status_code=503)


def _conversation_not_found() -> JSONResponse:
    return JSONResponse({"error": {"code": "conversation_not_found", "message": "대화를 찾을 수 없습니다."}}, status_code=404)


def _project_not_found() -> JSONResponse:
    return JSONResponse({"error": {"code": "project_not_found", "message": "프로젝트를 찾을 수 없습니다."}}, status_code=404)


def _usage_denied_response(decision) -> JSONResponse:
    headers = {}
    if decision.retry_after_seconds is not None:
        headers["Retry-After"] = str(decision.retry_after_seconds)
    return JSONResponse(
        {"error": {"code": decision.code, "message": decision.user_message}},
        status_code=decision.status_code,
        headers=headers,
    )


def _browser_refusal_reason(exc: BaseException) -> str:
    """#6921: a bounded ASCII label naming which contract rule refused the body."""
    if isinstance(exc, BrowserRequestError):
        return exc.reason
    if isinstance(exc, json.JSONDecodeError):
        return "json_decode"
    if isinstance(exc, UnicodeDecodeError):
        return "utf8_decode"
    return "value_error"


def _journal_browser_refusal(reason: str) -> None:
    """One ``ai_stage`` journal line per 422 so a refusal is diagnosable afterwards.

    #6921: the line carries the request id, the stage and the reason label only;
    the body, the user text and every request value stay out of the journal.
    """
    emit_stage_event(stage="browser.validate", outcome="error", duration_ms=0.0, code=reason)

def _login_required_response() -> JSONResponse:
    """Owner decision 2026-11-05: Chat AI answers require a signed-in member."""
    return JSONResponse(
        {"error": {"code": "login_required", "message": "AI 대화를 사용하려면 로그인이 필요합니다."}},
        status_code=401,
    )


def _public_sse(event: str, payload: dict[str, Any]) -> bytes:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {data}\n\n".encode("utf-8")


# #5573 no-deadline 설계 §7: a proxy between the browser and this Worker drops a
# response that has written nothing for a while, and the reader sees a dead turn.
# An SSE comment line is ignored by the EventSource grammar and by this app's own
# parser, so it keeps the connection open without becoming UI content. It is not a
# deadline: the shielded read below is never cancelled by a keepalive, so a turn
# that needs an hour still gets an hour.
SSE_KEEPALIVE = b": keepalive\n\n"
SSE_KEEPALIVE_SECONDS = 15.0
_KEEPALIVE_SENTINEL = object()


async def _stream_with_keepalive(stream, *, interval: float = SSE_KEEPALIVE_SECONDS):
    """Yield upstream events, and the sentinel whenever one gap reaches ``interval``."""

    iterator = stream.__aiter__()
    pending: asyncio.Future | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(iterator.__anext__())
            try:
                item = await asyncio.wait_for(asyncio.shield(pending), timeout=interval)
            except asyncio.TimeoutError:
                yield _KEEPALIVE_SENTINEL
                continue
            except StopAsyncIteration:
                return
            except asyncio.CancelledError:
                pending.cancel()
                raise
            pending = None
            yield item
    finally:
        # #5479: a client that left closes this generator at its yield point
        # (GeneratorExit, which is not a CancelledError); without this, the
        # shielded upstream read keeps running with nobody to receive it. The
        # paths that already settled the read leave it done, where this is a
        # no-op.
        if pending is not None and not pending.done():
            pending.cancel()


def _stream_json_error(exc: ChatRuntimeError) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": exc.code, "message": exc.user_message}},
        status_code=exc.status_code,
    )


def _empty_stream_json_error() -> JSONResponse:
    return JSONResponse(
        {"error": {"code": "empty_upstream_answer", "message": "AI가 표시할 답변을 만들지 못했습니다. 다시 시도해 주세요."}},
        status_code=502,
    )
# TTFB note: the stream route no longer returns these JSON errors after the
# first frame — once headers are on the wire the same code/message pair travels
# as an in-stream ``error`` frame the browser already renders. The helpers
# stay for callers that answer JSON before any streaming response exists.


async def _no_pc_tools() -> tuple[Any, ...]:
    """A project turn is never offered a PC tool (#5573); kept as its own awaitable
    so the guard read and the tool decision can run concurrently."""
    return ()


async def _close_stream(stream: Any) -> None:
    """Close a client stream chain on every route exit path.

    #4317: this close also runs while the response task is being cancelled
    (client disconnect mid-stream). A plain ``await closer()`` there inherits
    the pending cancellation, so the multi-layer generator chain ends up only
    partially unwound and the rest is left to asyncgen finalization — which on
    the Workers runtime surfaces as ``RuntimeError: async generator ignored
    GeneratorExit`` in the request logs even for a 200 answer. Shielding keeps
    the whole unwinding deterministic: the close finishes, the cancellation
    still propagates.
    """
    closer = getattr(stream, "aclose", None)
    if callable(closer):
        try:
            await asyncio.shield(closer())
        except asyncio.CancelledError:
            raise
        except Exception:
            pass


async def _chat_pc_tools_for_turn(
    request: Request, *, uid: str | None, model_id: str,
    user_text: str | None = None,
) -> tuple[Any, ...]:
    """The PC tool declaration for this turn, or an empty tuple.

    Tools require BOTH a verified PC target for this account and a resolved
    route whose catalog row declares native tools; otherwise the request keeps
    its existing shape and this turn has no PC path at all. The write tool is
    added only when the owner's own words asked for a change.
    """
    from .chat_pc_drive import pc_tools_for_turn, pc_tool_entry_available

    if not await pc_tool_entry_available(request, uid=uid, model_id=model_id):
        return ()
    return pc_tools_for_turn(user_text)


def _last_user_text(messages: Any) -> str:
    """The current turn's own words, which decide whether write is declared."""
    for message in reversed(messages or ()):
        if isinstance(message, Mapping) and message.get("role") == "user":
            content = message.get("content")
            return content if isinstance(content, str) else ""
    return ""


async def _no_connector_tools() -> tuple[Any, ...]:
    """A project turn is never offered a connector tool."""
    return ()


async def _chat_connector_tools_for_turn(
    request: Request, *, uid: str | None, intent: bool, model_id: str,
) -> tuple[Any, ...]:
    """The connector READ tool declarations for this turn, or an empty tuple.

    A connector-intent turn pays the grant check (3s budget, the same
    per-user cache the connection screen seeds): explicit Google naming, or a
    broad calendar/drive read intent whose service is connected. A general
    turn declares nothing and reads nothing. The resolved route must also
    declare native tools in the B14 catalog — the same gate the PC tools pass
    — because a route without that capability fails the stream before dispatch
    (measured: execution_failed at 0.46ms on a route whose row declares no
    tools). A project turn is never offered a connector tool.
    """
    from .chat_connector_tools import connector_tools_for_turn
    from .chat_pc_drive import chat_pc_route_declares_tools

    if not intent:
        return ()
    if not await chat_pc_route_declares_tools(request, model_id):
        return ()
    return await connector_tools_for_turn(request, uid=uid, intent_turn=intent)


#: The tool output becomes model context; the bound keeps one connector read
#: from crowding out the conversation the answer is written into.
_CONNECTOR_RESULT_CONTEXT_CHARS = 24_000


async def _connector_tool_lane(
    request: Request, *, tool_name: str, tool_arguments: Any,
    client: Any, messages: list, skill: Any,
    reference_context: str | None, conversation_id: str | None,
    uid: str | None, store: Any, latest_user: str | None,
    timing: ChatStreamTiming,
):
    """Execute one declared connector READ tool through the Engine, then answer.

    The Engine owns every authority decision (grant, scopes, allowlist); the
    lane only carries the closed tool identity from
    ``chat_connector_tools.CONNECTOR_TOOL_BINDINGS`` and the model's parsed
    arguments as data. The redacted tool output becomes model context for one
    plain follow-up dispatch — no tools are re-declared, so a connector read
    can never chain into another tool lane.
    """
    import time as _time

    from .chat_connector_tools import connector_tool_arguments_ok
    from .connector_tool_engine_client import ConnectorToolEngineError

    if not is_connector_tool_name(tool_name) or not connector_tool_arguments_ok(tool_arguments):
        timing.set_outcome("error")
        yield _public_sse(
            "error",
            {"error": {"code": "connector_tool_unsupported", "message": "요청한 커넥터 도구를 실행할 수 없습니다."}},
        )
        return
    engine_client = getattr(request.app.state, "connector_tool_engine_client", None)
    if engine_client is None:
        timing.set_outcome("error")
        yield _public_sse(
            "error",
            {"error": {"code": "connector_tool_unavailable", "message": "커넥터 도구를 사용할 수 없습니다."}},
        )
        return
    started = _time.perf_counter()
    try:
        tool = await engine_client.execute(
            tool_name=tool_name, arguments=dict(tool_arguments),
        )
    except ConnectorToolEngineError as exc:
        timing.set_outcome("error")
        emit_stage_event(
            stage="chat.connector_tools.execute", outcome="error",
            duration_ms=(_time.perf_counter() - started) * 1000.0, code=exc.code,
        )
        yield _public_sse("error", {"error": {"code": exc.code, "message": exc.message}})
        return
    except Exception:
        timing.set_outcome("error")
        emit_stage_event(
            stage="chat.connector_tools.execute", outcome="error",
            duration_ms=(_time.perf_counter() - started) * 1000.0,
            code="connector_tool_unavailable",
        )
        yield _public_sse(
            "error",
            {"error": {"code": "connector_tool_unavailable", "message": "커넥터 도구 실행에 실패했습니다. 다시 시도해 주세요."}},
        )
        return
    emit_stage_event(
        stage="chat.connector_tools.execute", outcome="ok",
        duration_ms=(_time.perf_counter() - started) * 1000.0, code=tool_name,
    )
    # The journal carries counts only (#7088): never a mail body, subject or
    # sender — the tool output itself travels to the model context alone.
    output = tool.get("output")
    result_items = None
    if isinstance(output, list):
        result_items = output
    elif isinstance(output, Mapping):
        for value in output.values():
            if isinstance(value, list):
                result_items = value
                break
    emit_stage_event(
        stage="chat.connector_tools.items", outcome="ok",
        duration_ms=0.0, code=f"items={len(result_items)}" if result_items is not None else None,
    )
    # Counts only (#7088): the host journal is stdout, so print it directly.
    print(
        f"connector_tools execute tool={tool_name} "
        f"items={len(result_items) if result_items is not None else '-'}",
        flush=True,
    )
    try:
        result_json = json.dumps(output, ensure_ascii=False)
    except (TypeError, ValueError):
        result_json = json.dumps({"unreadable": True}, ensure_ascii=False)
    if len(result_json) > _CONNECTOR_RESULT_CONTEXT_CHARS:
        result_json = result_json[:_CONNECTOR_RESULT_CONTEXT_CHARS] + " …(잘림)"
    result_context = "[connector:" + tool_name + " 결과]\n" + result_json

    follow = client.stream_text_auto(
        messages,
        skill=skill,
        additional_system_context=(
            reference_context + "\n\n" if reference_context else ""
        ) + result_context,
    )
    answer_parts: list[str] = []
    try:
        while True:
            try:
                event = await anext(follow)
            except StopAsyncIteration:
                timing.set_outcome("error")
                yield _public_sse(
                    "error",
                    {"error": {"code": "empty_upstream_answer", "message": "AI가 표시할 답변을 만들지 못했습니다. 다시 시도해 주세요."}},
                )
                return
            if getattr(event, "delta_thought", None):
                yield _public_sse("thought", {"text": event.delta_thought})
                continue
            if event.delta_content:
                answer_parts.append(event.delta_content)
                yield _public_sse("delta", {"delta": event.delta_content})
            if event.done:
                break
    except ChatRuntimeError as exc:
        timing.set_outcome("error")
        yield _public_sse("error", {"error": {"code": exc.code, "message": exc.user_message}})
        return
    except asyncio.CancelledError:
        raise
    except Exception:
        timing.set_outcome("error")
        yield _public_sse(
            "error",
            {"error": {"code": "upstream_route_error", "message": "답변을 불러오지 못했습니다. 다시 시도해 주세요."}},
        )
        return
    answer = "".join(answer_parts)
    if not answer:
        timing.set_outcome("error")
        yield _public_sse(
            "error",
            {"error": {"code": "empty_upstream_answer", "message": "AI가 표시할 답변을 만들지 못했습니다. 다시 시도해 주세요."}},
        )
        return
    timing.set_outcome("tool_lane")
    done_payload: dict[str, Any] = {"done": True}
    if uid is not None and store is not None and latest_user:
        try:
            saved_id = await store.append_exchange(
                uid, conversation_id, latest_user, answer, product_scope=PRODUCT_SCOPE_CHAT,
            )
        except Exception:
            saved_id = None
        if saved_id is not None:
            done_payload["conversation_id"] = saved_id
    yield _public_sse("done", done_payload)


def _model_history_incomplete() -> JSONResponse:
    return JSONResponse(
        {"error": {"code": "conversation_context_incomplete",
                   "message": "이전 대화 원문을 복원할 수 없습니다. 원문을 다시 입력하거나 새 대화를 시작해 주세요."}},
        status_code=409,
    )


def _model_history_too_large() -> JSONResponse:
    return JSONResponse(
        {"error": {"code": "model_context_transport_limit",
                   "message": "전체 대화가 서버 전송 안전 용량을 초과했습니다. 새 대화를 시작하거나 문맥을 나눠 주세요."}},
        status_code=413,
    )


def _custom_error_response(exc: CustomProviderError) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": exc.code, "message": exc.user_message}},
        status_code=exc.status_code,
    )


def _custom_selection_unsupported(exc: CustomProviderSelectionError) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": "custom_provider_unsupported", "message": str(exc)}},
        status_code=422,
    )


async def _complete_custom_chat(
    request: Request,
    *,
    uid: str,
    selection: CustomModelSelection,
    messages: list[dict[str, str]],
    reference_context: str | None,
) -> dict[str, Any]:
    """Route an owner's key through B14 when enabled, otherwise directly."""
    from .byok_bridge import enabled, resolve_reference
    if enabled(request.app.state):
        from .orchestration_bridge import B62OrchestrationError
        import uuid

        resolved = await resolve_reference(request.app.state, uid, selection)
        if resolved is None:
            raise CustomProviderError(
                422, "user_credential_unsupported_via_b14",
                "이 공급자 또는 주소는 B14 경유를 지원하지 않습니다.",
            )
        bridge = getattr(request.app.state, "orchestration_bridge", None)
        if bridge is None:
            raise CustomProviderError(503, "orchestration_unavailable", "AI 연결을 사용할 수 없습니다.")
        model_id, credential_ref = resolved
        try:
            result = await bridge.start(
                user_id=uid, messages=messages, skill=None, model_id=model_id,
                user_text=next((m["content"] for m in reversed(messages) if m["role"] == "user"), ""),
                conversation_id=None, subject_id=None,
                session_id="byok_" + uuid.uuid4().hex,
                user_credential_ref=credential_ref,
                byok_selection={"provider": selection.provider, "model": selection.model},
                reasoning_effort=selection.reasoning_effort,
                additional_system_context=reference_context,
            )
            answer = result.answer
            if not isinstance(answer, str) or not answer.strip():
                raise CustomProviderError(502, "malformed_upstream", "AI 답변을 확인할 수 없습니다.")
            return {"answer": answer}
        except B62OrchestrationError as exc:
            raise CustomProviderError(exc.status_code, exc.code, exc.user_message) from None
    return await complete_owner_custom(
        request.app.state,
        uid=uid,
        selection=selection,
        messages=messages,
        reasoning_effort=selection.reasoning_effort,
        system_context=reference_context,
    )


async def _restore_owner_chat_model_messages(
    store: HistoryStore,
    owner_id: str,
    conversation_id: str,
    verified_conversation: dict[str, Any],
    browser_messages: list[dict[str, str]],
    *,
    owned_context: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Never use displayed D1 excerpts or untrusted browser history as model truth.

    The last user turn is the new submitted prompt. All previous turns are
    obtained exclusively from the owner-scoped server store; browsers cannot
    replace existing assistant turns or smuggle a preview as full context.
    ``owned_context`` is an already-fetched full-context projection (the stream
    route reads it in parallel with the existence check); when it is absent the
    projection is fetched here exactly as before.
    """
    newest = next((item for item in reversed(browser_messages) if item["role"] == "user"), None)
    if newest is None:
        raise HistoryContextIncomplete("new user turn is missing")
    if owned_context is not None:
        owned = owned_context
    else:
        get_full = getattr(store, "get_conversation_model_context", None)
        # D1 production always implements the private full-context projection;
        # older test-only/in-memory stores retain their already-owner-scoped data.
        owned = await get_full(owner_id, conversation_id, product_scope=PRODUCT_SCOPE_CHAT) if callable(get_full) else verified_conversation
    if owned is None or owned.get("id") != conversation_id:
        raise HistoryContextIncomplete("owner model conversation unavailable")
    rows = owned.get("messages")
    if not isinstance(rows, list):
        raise HistoryContextIncomplete("saved model conversation is malformed")
    normalized: list[dict[str, str]] = []
    byte_total = len(newest["content"].encode("utf-8"))
    for row in rows:
        if not isinstance(row, dict) or row.get("role") not in {"user", "assistant"}:
            raise HistoryContextIncomplete("saved model conversation has invalid role")
        content = row.get("content")
        if not isinstance(content, str) or not content.strip():
            raise HistoryContextIncomplete("saved model conversation has invalid text")
        if len(content) == MAX_HISTORY_MESSAGE_CHARS and content.endswith(HISTORY_PREVIEW_SUFFIX):
            raise HistoryContextIncomplete("saved model context is an incomplete preview")
        byte_total += len(content.encode("utf-8"))
        if byte_total > MAX_MODEL_CONTEXT_BYTES:
            raise OverflowError("owned model conversation exceeds transport guard")
        normalized.append({"role": row["role"], "content": content})
    if byte_total > MAX_MODEL_CONTEXT_BYTES:
        raise OverflowError("owned model conversation exceeds transport guard")
    normalized.append(dict(newest))
    return normalized


async def api_chat_stream(request: Request):
    timing = ChatStreamTiming()
    try:
        response = await _api_chat_stream_body(request, timing)
        if not isinstance(response, StreamingResponse):
            # A JSON rejection never enters a response generator: log how far
            # this request got. A streaming response logs from its own body.
            timing.emit()
        return response
    except Exception:
        timing.emit()
        raise


async def _api_chat_stream_body(request: Request, timing: ChatStreamTiming):
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if (
                MAX_BROWSER_BODY_BYTES is not None
                and int(content_length) > MAX_BROWSER_BODY_BYTES
            ):
                return _too_large_response()
        except ValueError:
            _journal_browser_refusal("content_length_invalid")
            return JSONResponse({"error": {"code": "invalid_request", "message": "요청 형식이 올바르지 않습니다."}}, status_code=422)
    try:
        body = await read_bounded_request_body(request, max_bytes=MAX_BROWSER_BODY_BYTES)
    except RequestBodyTooLarge:
        return _too_large_response()

    try:
        raw = (_decode_completed_binary_attachment(body) if request.url.path == "/api/chat" and request.headers.get("content-type", "").split(";", 1)[0].strip().lower() == "application/octet-stream" else json.loads(body.decode("utf-8")))
        messages, skill, tool_request, attachments, conversation_id, browser_project_id, custom = await _validate_payload_async(raw, file_resolver=file_resolver(request))
        if custom is None:
            # No-tier browser clients resolve the Free product tier; an
            # explicit browser tier rides the request context.
            selected_model, messages = _apply_b62_model_policy(
                messages,
                tier_id=raw.get("tier", "free"),
            )
        else:
            selected_model = custom.model
    except (UnicodeDecodeError, json.JSONDecodeError, BrowserRequestError, ValueError) as exc:
        _journal_browser_refusal(_browser_refusal_reason(exc))
        message = str(exc) if isinstance(exc, BrowserRequestError) else "요청 형식이 올바르지 않습니다."
        return JSONResponse({"error": {"code": exc.code if isinstance(exc, BrowserRequestError) else "invalid_request", "message": message}}, status_code=422)
    timing.mark("validated")

    if tool_request is not None or attachments:
        _journal_browser_refusal("streaming_unsupported")
        return JSONResponse(
            {"error": {"code": "streaming_unsupported", "message": "스트리밍 채팅은 현재 일반 텍스트 질문만 지원합니다."}},
            status_code=422,
        )

    uid = current_user_id(request) if auth_ready(request) else None
    # Owner decision 2026-11-05: Chat/Claw AI answers are signed-in only.
    # "Free without a login" is gone; a signed-in member keeps the Free tier.
    # The mock runtime is the network-free CI harness and stays available.
    if uid is None and getattr(getattr(request.app.state, "settings", None), "runtime_mode", None) != "mock":
        return _login_required_response()
    if custom is not None and uid is None:
        return JSONResponse(
            {"error": {"code": "unauthorized", "message": "PADIEM Custom을 사용하려면 로그인이 필요합니다."}},
            status_code=401,
        )
    if "tier" in raw:
        if raw.get("tier") == "admin":
            admin_denial = await selected_admin_denial(request, uid)
            if admin_denial is not None:
                return admin_denial
        else:
            tier_denial = await selected_grade_denial(request, uid, raw["tier"])
            if tier_denial is not None:
                return tier_denial
    store: HistoryStore | None = getattr(request.app.state, "history_store", None)
    project_file_store: ProjectFileStore | None = request.app.state.project_file_store
    if browser_project_id is not None and uid is None:
        return JSONResponse({"error": {"code": "unauthorized", "message": "프로젝트를 사용하려면 로그인이 필요합니다."}}, status_code=401)

    effective_project_id = browser_project_id
    if uid is not None and store is not None and conversation_id is not None:
        # The existence check and the private full-context projection are two
        # independent owner-scoped reads of the same conversation: run them
        # concurrently so a stored thread does not pay both serially.
        existing_task = store.get_conversation(uid, conversation_id, product_scope=PRODUCT_SCOPE_CHAT)
        get_full = getattr(store, "get_conversation_model_context", None)
        model_context_task = (
            get_full(uid, conversation_id, product_scope=PRODUCT_SCOPE_CHAT)
            if callable(get_full) else None
        )
        if model_context_task is not None:
            existing_conversation, owned_context = await asyncio.gather(existing_task, model_context_task, return_exceptions=True)
            # The existence check keeps its old precedence and its own error
            # contract; the projection read keeps the restore contract's
            # exception types (incomplete 409, overflow 413, else 503).
            if isinstance(existing_conversation, BaseException):
                return _history_unavailable()
            if existing_conversation is None:
                return _conversation_not_found()
            if isinstance(owned_context, BaseException):
                if isinstance(owned_context, HistoryContextIncomplete):
                    return _model_history_incomplete()
                if isinstance(owned_context, OverflowError):
                    return _model_history_too_large()
                return _history_unavailable()
        else:
            try:
                existing_conversation = await existing_task
            except Exception:
                return _history_unavailable()
            owned_context = None
        if existing_conversation is None:
            return _conversation_not_found()
        stored_project_id = existing_conversation.get("project_id")
        if stored_project_id is not None and not isinstance(stored_project_id, str):
            return _conversation_not_found()
        if browser_project_id is not None and browser_project_id != stored_project_id:
            return _conversation_not_found()
        if browser_project_id is None:
            effective_project_id = stored_project_id
        try:
            messages = await _restore_owner_chat_model_messages(
                store, uid, conversation_id, existing_conversation, messages,
                owned_context=owned_context,
            )
        except HistoryContextIncomplete:
            return _model_history_incomplete()
        except OverflowError:
            return _model_history_too_large()
        except Exception:
            return _history_unavailable()
    timing.mark("history")

    project = None
    project_context = None
    project_files_context = None
    project_files_used = 0
    if effective_project_id is not None:
        if uid is None or store is None:
            return JSONResponse({"error": {"code": "unauthorized", "message": "프로젝트를 사용하려면 로그인이 필요합니다."}}, status_code=401)
        # The project row and its file listing are independent reads: start
        # both now, await each with its own error contract.
        project_task = store.get_project(uid, effective_project_id)
        files_task = (
            project_file_store.list_files(uid, effective_project_id)
            if project_file_store is not None else None
        )
        try:
            project = await project_task
        except Exception:
            return _history_unavailable()
        if project is None:
            return _project_not_found()
        project_context = build_project_context(project)
        if files_task is not None:
            try:
                project_files = await files_task
            except Exception:
                return _project_files_unavailable()
            project_files_context, project_files_used = build_project_files_context(project_files)
    timing.mark("project")

    reference_context = combine_reference_context(project_context, project_files_context, None)

    # PADIEM Custom: the owner's key goes directly to the explicitly selected
    # provider. No B14 binding/router/registry/default/fallback/secret lookup
    # happens on this path, so it stays usable while B14 is unavailable.
    if custom is not None:
        try:
            custom_result = await _complete_custom_chat(
                request,
                uid=uid,
                selection=custom,
                messages=messages,
                reference_context=reference_context,
            )
        except CustomProviderSelectionError as exc:
            return _custom_selection_unsupported(exc)
        except CustomProviderError as exc:
            return _custom_error_response(exc)
        custom_answer = custom_result["answer"]
        custom_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), None)

        async def custom_body_iterator():
            yield _public_sse("delta", {"delta": custom_answer})
            custom_done: dict[str, Any] = {"done": True}
            if uid is not None and store is not None and custom_user:
                try:
                    if effective_project_id is None:
                        saved_id = await store.append_exchange(
                            uid, conversation_id, custom_user, custom_answer,
                            product_scope=PRODUCT_SCOPE_CHAT,
                        )
                    else:
                        saved_id = await store.append_exchange(
                            uid, conversation_id, custom_user, custom_answer,
                            project_id=effective_project_id,
                            product_scope=PRODUCT_SCOPE_CHAT,
                        )
                except HistoryForbidden:
                    yield _public_sse(
                        "error",
                        {"error": {"code": "conversation_not_found", "message": "대화를 찾을 수 없습니다."}},
                    )
                    return
                except Exception:
                    saved_id = None
                if saved_id is not None:
                    custom_done["conversation_id"] = saved_id
                    if effective_project_id is not None:
                        custom_done["project_id"] = effective_project_id
            yield _public_sse("done", custom_done)

        async def custom_timing_iterator():
            try:
                async for chunk in custom_body_iterator():
                    yield chunk
            finally:
                timing.emit()

        return StreamingResponse(
            custom_timing_iterator(),
            status_code=200,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"},
        )

    latest_user_text = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    identity_question = is_padiem_identity_question(latest_user_text)

    async def _drive_preflight() -> tuple[str | None, tuple[dict[str, str], ...]]:
        if identity_question:
            return (None, ())
        return await drive_general_grounding(request, latest_user_text)

    async def _pc_preflight() -> str | None:
        if uid is None:
            return None
        from .pc_work_context import build_pc_work_context_text

        try:
            result = await build_pc_work_context_text(request, owner_id=uid)
        except Exception:
            return None
        return result if isinstance(result, str) else None

    async def _usage_preflight():
        if not request.app.state.usage_gate_enforced:
            return None
        usage_gate: UsageGate = request.app.state.usage_gate
        return await usage_gate.authorize(
            raw_ip=request.headers.get("cf-connecting-ip"),
            user_id=uid,
        )

    # Drive/PC context, the PC work context and the usage-gate decision are
    # independent of one another: one gather instead of two serial waits. The
    # gate's own exception still propagates (never swallowed into a skip).
    drive_result, pc_work_result, usage_decision = await asyncio.gather(
        _drive_preflight(), _pc_preflight(), _usage_preflight(), return_exceptions=True,
    )
    timing.mark("preflight")

    if isinstance(drive_result, DriveGroundingError):
        return JSONResponse({"error": {"code": drive_result.code, "message": drive_result.message}}, status_code=drive_result.status_code)

    if isinstance(drive_result, BaseException):
        drive_result = (None, ())

    drive_context, drive_sources = drive_result if isinstance(drive_result, tuple) else (None, ())
    if drive_context:
        reference_context = (reference_context + "\n\n" if reference_context else "") + drive_context
    if isinstance(pc_work_result, str):
        reference_context = (
            reference_context + "\n\n" if reference_context else ""
        ) + pc_work_result

    if isinstance(usage_decision, BaseException):
        raise usage_decision
    if usage_decision is not None and not usage_decision.allowed:
        return _usage_denied_response(usage_decision)
    timing.mark("usage")

    timezone_name = raw.get("timezone") if isinstance(raw.get("timezone"), str) else None
    calendar_store = getattr(request.app.state, "calendar_store", None)
    util_scope = declared_util_scope(raw)
    # A connector question belongs to the connector READ tools on this same
    # turn, never to the workspace-native calendar store. Explicit Google
    # naming always qualifies; a broad read intent qualifies only when the
    # named service's grant is connected.
    if browser_project_id is None:
        google_connector_turn = await google_connector_turn_for_text(
            request, uid=uid, user_text=latest_user_text,
        )
    else:
        # A project turn is never offered a connector tool; keep its existing
        # explicit-Google/native-calendar behavior without broad promotion.
        google_connector_turn = google_connector_intent(latest_user_text)
    needs_native_calendar = False
    if util_scope is None and not google_connector_turn:
        try:
            needs_native_calendar = parse_native_calendar_intent(latest_user_text, timezone_name=timezone_name)["op"] != "none"
        except Exception:
            needs_native_calendar = False
    if needs_native_calendar and calendar_store is None:
        return JSONResponse({"error": {"code": "calendar_store_unavailable", "message": "Calendar storage is unavailable"}}, status_code=503)
    if calendar_store is not None and util_scope is None and not google_connector_turn:
        try:
            client_turn_id = raw.get("calendar_turn_id")
            if not isinstance(client_turn_id, str):
                client_turn_id = request.headers.get("X-Padiem-Calendar-Turn-Id")
            if not isinstance(client_turn_id, str) or not client_turn_id or len(client_turn_id) > 128:
                client_turn_id = None
            material = "|" + client_turn_id if client_turn_id is not None else ""
            turn_key = "chat-" + str(uid) + "-" + str(conversation_id or "anon") + "-" + str(len(messages)) + "-" + (__import__("hashlib").sha256("|".join((str(latest_user_text), str(timezone_name or ""), material)).encode("utf-8")).hexdigest()[:16])
            native_result = await try_native_calendar_chat(
                request, calendar_store, uid,
                messages, timezone_name=timezone_name,
                turn_key=turn_key,
            )
        except NativeCalendarAdapterError as exc:
            return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status_code)
        except Exception:
            native_result = None
        if needs_native_calendar and native_result is None:
            return JSONResponse({"error": {"code": "calendar_unavailable", "message": "native calendar unavailable"}}, status_code=503)
        if native_result is not None:
            answer = str(native_result.get("answer", ""))
            async def native_body_iterator():
                yield _public_sse("delta", {"delta": answer})
                if uid is not None and store is not None and latest_user_text:
                    try:
                        saved_id = await store.append_exchange(uid, conversation_id, latest_user_text, answer, product_scope=PRODUCT_SCOPE_CHAT)
                    except Exception:
                        saved_id = None
                    done_payload = {"done": True}
                    if saved_id is not None:
                        done_payload["conversation_id"] = saved_id
                    yield _public_sse("done", done_payload)
                    return
                yield _public_sse("done", {"done": True})
            async def native_timing_iterator():
                try:
                    async for chunk in native_body_iterator():
                        yield chunk
                finally:
                    timing.emit()

            return StreamingResponse(
                native_timing_iterator(),
                status_code=200,
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"},
            )

    timing.mark("calendar")
    auto_grounding: AutoGroundingService = request.app.state.auto_grounding
    grounding_notice = {}
    auto_plan = None
    try:
        auto_plan = None if (drive_context or identity_question) else await auto_grounding.prepare(
            messages,
            skill=skill,
            additional_system_context=reference_context,
            util_scope=util_scope,
            **({"explicit_search": True} if raw.get("web_search") else {}),
        )
    except GroundingError as exc:
        grounding_notice = grounding_fallback_fields(exc)
    if getattr(auto_plan, "error", None) is not None:
        grounding_notice = grounding_fallback_fields(auto_plan.error)
    if auto_plan is not None and auto_plan.prepared is not None:
        reference_context = auto_plan.prepared.context
        # The auto-grounding plan replaces the context it was handed; the
        # verified PC state must still reach this model call (#5015).
        if pc_work_result:
            reference_context = (
                reference_context + "\n\n" if reference_context else ""
            ) + pc_work_result

    client: B14Client = request.app.state.b14_client
    timing.mark("grounding")
    async with chat_request_tier_context(request, raw.get("tier", "free")) as tier_binding:
        tier_id, route_model = tier_binding
        policy = resolve_request_model_policy(messages)
        # The dispatch guard, the PC tool offer and the connector READ offer
        # are independent reads: run them concurrently instead of paying them
        # serially before dispatch. The connector check is bounded (30s cache,
        # 300ms budget) and declares nothing on a slow or failed check.
        guard, pc_tools, connector_tools = await asyncio.gather(
            create_guard_from_request(
                request,
                policy.model_id,
                request.app.state.central_model_policy_store,
                request.app.state.b14_catalog_source,
            ),
            _chat_pc_tools_for_turn(request, uid=uid, model_id=policy.model_id, user_text=_last_user_text(messages))
            if browser_project_id is None else _no_pc_tools(),
            _chat_connector_tools_for_turn(request, uid=uid, intent=google_connector_turn, model_id=policy.model_id)
            if browser_project_id is None else _no_connector_tools(),
        )
        if isinstance(guard, BaseException):
            raise guard
        if isinstance(pc_tools, BaseException):
            raise pc_tools
        if isinstance(connector_tools, BaseException):
            # The connector offer must never fail the turn: declare nothing.
            connector_tools = ()
        client = apply_guard_to_client(client, guard)
        turn_tools = pc_tools + connector_tools
        # #5573 (3-B-2): only a verified PC account on a tools-declaring route
        # receives the PC tools; every other turn keeps the request bytes it
        # had before this slice. A project turn runs on its own reference
        # context and is never offered a PC tool, so it can neither be deferred
        # nor handed to the PC lane. Connector READ tools join the same
        # declaration only when the bounded grant check said "granted".
        stream = client.stream_text_auto(
            messages,
            skill=skill,
            additional_system_context=reference_context,
            **({"tools": turn_tools, "tool_choice": "auto"} if turn_tools else {}),
        )
        timing.mark("lane")
        latest_user = next((item["content"] for item in reversed(messages) if item["role"] == "user"), None)

        async def body_iterator():
            # The model dispatch runs here, after the response headers and the
            # accepted frame are already on the wire: a slow first token can
            # no longer hold the browser's first byte hostage. The server-
            # resolved tier binding is re-bound for this response task because
            # identity and policy read the request tier at dispatch time.
            with request_tier_context(tier_id, model_id=route_model):
                timing.mark("dispatch")
                yield _public_sse("meta", {"stream": True})
                timing.mark("flushed")
                answer_parts: list[str] = []
                try:
                    first_visible = None
                    tool_call = None
                    first_byte_marked = False
                    try:
                        while True:
                            try:
                                event = await anext(stream)
                            except StopAsyncIteration:
                                timing.set_outcome("error")
                                yield _public_sse(
                                    "error",
                                    {"error": {"code": "empty_upstream_answer", "message": "AI가 표시할 답변을 만들지 못했습니다. 다시 시도해 주세요."}},
                                )
                                return
                            candidate = getattr(event, "tool_call", None)
                            if candidate is not None:
                                if getattr(event, "delta_thought", None):
                                    if not first_byte_marked:
                                        first_byte_marked = True
                                        timing.mark("first_token")
                                    yield _public_sse("thought", {"text": event.delta_thought})
                                tool_call = candidate
                                break
                            if getattr(event, "delta_thought", None):
                                # A thinking summary is the first visible byte;
                                # it is shown beside the answer, never inside it.
                                if not first_byte_marked:
                                    first_byte_marked = True
                                    timing.mark("first_token")
                                yield _public_sse("thought", {"text": event.delta_thought})
                                continue
                            if event.delta_content:
                                first_visible = event
                                timing.mark("first_token")
                                break
                            if event.done:
                                timing.set_outcome("error")
                                yield _public_sse(
                                    "error",
                                    {"error": {"code": "empty_upstream_answer", "message": "AI가 표시할 답변을 만들지 못했습니다. 다시 시도해 주세요."}},
                                )
                                return
                    except ChatRuntimeError as exc:
                        timing.set_outcome("error")
                        yield _public_sse("error", {"error": {"code": exc.code, "message": exc.user_message}})
                        return
                    except asyncio.CancelledError:
                        timing.set_outcome("cancelled")
                        raise
                    except Exception:
                        # Same safe boundary the pre-TTFB JSON contract had for
                        # an unexpected dispatch-stage failure.
                        timing.set_outcome("error")
                        yield _public_sse(
                            "error",
                            {"error": {"code": "upstream_route_error", "message": "답변을 불러오지 못했습니다. 다시 시도해 주세요."}},
                        )
                        return
                    if tool_call is not None:
                        # The model asked for a PC tool instead of an answer.
                        # Stop reading the stream and let the PC lane re-verify
                        # the owner, grant and target before it executes
                        # anything. The lane's frames ride this same response.
                        await _close_stream(stream)
                        from .chat_pc_drive import (
                            ChatPCDriveError,
                            chat_pc_plan_for_tool,
                            execute_chat_pc_drive_lane,
                        )

                        selected_tool = getattr(tool_call, "name", None)
                        if isinstance(selected_tool, str) and is_connector_tool_name(selected_tool):
                            # The model asked for a connector READ tool. The
                            # Engine re-verifies the grant and scopes on its
                            # own execute path; the lane carries only the
                            # closed tool identity and the parsed arguments.
                            await _close_stream(stream)
                            async for frame in _connector_tool_lane(
                                request,
                                tool_name=selected_tool,
                                tool_arguments=getattr(tool_call, "arguments", None),
                                client=client,
                                messages=messages,
                                skill=skill,
                                reference_context=reference_context,
                                conversation_id=conversation_id,
                                uid=uid,
                                store=store,
                                latest_user=latest_user,
                                timing=timing,
                            ):
                                yield frame
                            return
                        declared_plan = (
                            chat_pc_plan_for_tool(selected_tool)
                            if isinstance(selected_tool, str) else None
                        )
                        if declared_plan is None:
                            timing.set_outcome("error")
                            yield _public_sse(
                                "error",
                                {"error": {"code": "chat_pc_tool_unsupported", "message": "요청한 PC 도구를 실행할 수 없습니다."}},
                            )
                            return
                        from .pc_action_context import build_pc_action_context

                        execution_user_text = next(
                            (item["content"] for item in reversed(policy.messages)
                             if item.get("role") == "user"),
                            None,
                        )
                        try:
                            # The browser's own run handle is reused as the
                            # staged run id, so a dropped connection recovers
                            # this turn's verified result through the existing
                            # owner-scoped GET (#5567) instead of resubmitting
                            # the PC turn.
                            lane_outcome = await execute_chat_pc_drive_lane(
                                request,
                                user_text=latest_user_text,
                                execution_user_text=execution_user_text,
                                skill=skill,
                                model_id=selected_model,
                                conversation_id=conversation_id,
                                device_id=raw.get("device_id"),
                                run_id=raw.get("pc_run_id"),
                                conversation_messages=messages,
                                pc_action_context=build_pc_action_context(
                                    messages, user_text=latest_user_text,
                                    trusted_history=(conversation_id is not None and uid is not None and store is not None),
                                    tool_results=(
                                        ("file", project_files_context), ("file", drive_context),
                                        ("web", getattr(getattr(auto_plan, "prepared", None), "context", None)),
                                    ),
                                ),
                                selected_tool=selected_tool,
                                declared_plan=declared_plan,
                            )
                        except ChatPCDriveError as exc:
                            timing.set_outcome("error")
                            yield _public_sse("error", {"error": exc.public_error()})
                            return
                        if lane_outcome is None:
                            timing.set_outcome("error")
                            yield _public_sse(
                                "error",
                                {"error": {"code": "chat_pc_lane_unavailable", "message": "PC 작업을 시작하지 못했습니다. 다시 시도해 주세요."}},
                            )
                            return
                        lane_answer, lane_conversation_id = lane_outcome
                        from .chat_pc_drive import pc_scope_notice_for_run

                        lane_scope_notice = await pc_scope_notice_for_run(
                            request, run_id=raw.get("pc_run_id"),
                        )
                        timing.set_outcome("tool_lane")
                        yield _public_sse("delta", {"delta": lane_answer})
                        tool_done: dict[str, Any] = {"done": True}
                        if lane_conversation_id:
                            tool_done["conversation_id"] = lane_conversation_id
                        if lane_scope_notice:
                            # #5573: the scope pinned before dispatch is its own
                            # field, so the live answer states "목록만 조회합니다"
                            # without the notice being folded into the answer text.
                            tool_done["scope_notice"] = lane_scope_notice
                        yield _public_sse("done", tool_done)
                        return

                    assert first_visible is not None and first_visible.delta_content
                    first_delta = first_visible.delta_content
                    answer_parts = [first_delta]
                    yield _public_sse("delta", {"delta": first_delta})
                    async for item in _stream_with_keepalive(stream):
                        if item is _KEEPALIVE_SENTINEL:
                            yield SSE_KEEPALIVE
                            continue
                        event = item
                        if getattr(event, "delta_thought", None):
                            yield _public_sse("thought", {"text": event.delta_thought})
                        if event.delta_content:
                            answer_parts.append(event.delta_content)
                            yield _public_sse("delta", {"delta": event.delta_content})
                        if event.done:
                            done_payload: dict[str, Any] = {"done": True}
                            done_payload.update(grounding_notice)
                            if auto_plan is not None and auto_plan.prepared is not None:
                                done_payload["answer_status"] = "answered_with_evidence"
                                done_payload["evidence"] = _public_evidence(auto_plan.prepared.evidence)
                                done_payload["tool"] = {"id": "web_search", "title": "웹 검색"}
                            if drive_sources:
                                done_payload["answer_status"] = "answered_with_evidence"
                                done_payload["evidence"] = [
                                    {"id": f"drive-{i}", "title": src["title"], "url": src["url"],
                                     "retrieved_at": src["retrieved_at"], "source_type": "google_drive"}
                                    for i, src in enumerate(drive_sources, 1)
                                ]
                            if uid is not None and store is not None and latest_user:
                                answer = "".join(answer_parts)
                                try:
                                    if effective_project_id is None:
                                        saved_id = await store.append_exchange(uid, conversation_id, latest_user, answer, product_scope=PRODUCT_SCOPE_CHAT)
                                    else:
                                        saved_id = await store.append_exchange(
                                            uid,
                                            conversation_id,
                                            latest_user,
                                            answer,
                                            project_id=effective_project_id,
                                            product_scope=PRODUCT_SCOPE_CHAT,
                                        )
                                except HistoryForbidden:
                                    yield _public_sse(
                                        "error",
                                        {"error": {"code": "conversation_not_found", "message": "대화를 찾을 수 없습니다."}},
                                    )
                                    return
                                except Exception:
                                    saved_id = None
                                if saved_id is not None:
                                    done_payload["conversation_id"] = saved_id
                                    if effective_project_id is not None:
                                        done_payload["project_id"] = effective_project_id
                                        done_payload["project"] = (
                                            {"id": project.id, "name": project.name}
                                            if project is not None
                                            else None
                                        )
                            if project_files_used:
                                done_payload["project_files_used"] = project_files_used
                            yield _public_sse("done", done_payload)
                            return

                    yield _public_sse(
                        "error",
                        {"error": {"code": "malformed_upstream", "message": "AI 응답 형식을 확인할 수 없습니다. 다시 시도해 주세요."}},
                    )
                except ChatRuntimeError as exc:
                    timing.set_outcome("error")
                    yield _public_sse(
                        "error",
                        {"error": {"code": exc.code, "message": exc.user_message}},
                    )
                except asyncio.CancelledError:
                    timing.set_outcome("cancelled")
                    raise
                except Exception:
                    timing.set_outcome("error")
                    yield _public_sse(
                        "error",
                        {"error": {"code": "stream_error", "message": "스트리밍 답변을 계속하지 못했습니다. 다시 시도해 주세요."}},
                    )
                finally:
                    await _close_stream(stream)
                    timing.emit()

        return StreamingResponse(
            body_iterator(),
            status_code=200,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-store",
                "X-Accel-Buffering": "no",
            },
        )


# #2505: the frame decoder moved to ``app/binary_attachment_frame.py`` so the
# Claw lane reads the same bytes. The module-level alias keeps every existing
# Chat import (and its test) working unchanged.
_decode_completed_binary_attachment = decode_binary_attachment_frame


async def api_chat(request: Request) -> JSONResponse:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if (
                MAX_BROWSER_BODY_BYTES is not None
                and int(content_length) > MAX_BROWSER_BODY_BYTES
            ):
                return _too_large_response()
        except ValueError:
            _journal_browser_refusal("content_length_invalid")
            return JSONResponse({"error": {"code": "invalid_request", "message": "요청 형식이 올바르지 않습니다."}}, status_code=422)
    try:
        body = await read_bounded_request_body(request, max_bytes=MAX_BROWSER_BODY_BYTES)
    except RequestBodyTooLarge:
        return _too_large_response()

    try:
        raw = (_decode_completed_binary_attachment(body) if request.url.path == "/api/chat" and request.headers.get("content-type", "").split(";", 1)[0].strip().lower() == "application/octet-stream" else json.loads(body.decode("utf-8")))
        messages, skill, tool_request, attachments, conversation_id, browser_project_id, custom = await _validate_payload_async(raw, file_resolver=file_resolver(request))
        if custom is None:
            # No-tier browser clients resolve the Free product tier; an
            # explicit browser tier rides the request context.
            selected_model, messages = _apply_b62_model_policy(
                messages,
                tier_id=raw.get("tier", "free"),
            )
        else:
            selected_model = custom.model
    except (UnicodeDecodeError, json.JSONDecodeError, BrowserRequestError, ValueError) as exc:
        _journal_browser_refusal(_browser_refusal_reason(exc))
        message = str(exc) if isinstance(exc, BrowserRequestError) else "요청 형식이 올바르지 않습니다."
        return JSONResponse({"error": {"code": exc.code if isinstance(exc, BrowserRequestError) else "invalid_request", "message": message}}, status_code=422)

    settings: Settings = request.app.state.settings
    if selected_model == FREE_B14_MODEL_ID and any(isinstance(item, ImageAttachment) for item in attachments):
        selected_model = FREE_FALLBACK_B14_MODEL_ID
    if settings.runtime_mode == "b14" and any(isinstance(item, ImageAttachment) for item in attachments):
        if not model_supports(selected_model, "image"):
            return JSONResponse(
                {
                    "error": {
                        "code": "image_model_unavailable",
                        "message": "현재 선택된 AI 모델은 사진 입력을 지원하지 않습니다. 사진 지원 모델이 준비되면 다시 이용해 주세요.",
                    }
                },
                status_code=503,
            )

    if tool_request is not None and tool_request.tool.id == "deep_research":
        if settings.runtime_mode != "b14" or settings.web_provider not in {"mock", "firecrawl"}:
            return JSONResponse(
                {"error": {"code": "deep_research_unavailable", "message": "심층 리서치를 현재 사용할 수 없습니다."}},
                status_code=503,
            )

    uid = current_user_id(request) if auth_ready(request) else None
    # Owner decision 2026-11-05: Chat/Claw AI answers are signed-in only.
    # "Free without a login" is gone; a signed-in member keeps the Free tier.
    # The mock runtime is the network-free CI harness and stays available.
    if uid is None and getattr(getattr(request.app.state, "settings", None), "runtime_mode", None) != "mock":
        return _login_required_response()
    if custom is not None and uid is None:
        return JSONResponse(
            {"error": {"code": "unauthorized", "message": "PADIEM Custom을 사용하려면 로그인이 필요합니다."}},
            status_code=401,
        )
    if "tier" in raw:
        if raw.get("tier") == "admin":
            admin_denial = await selected_admin_denial(request, uid)
            if admin_denial is not None:
                return admin_denial
        else:
            tier_denial = await selected_grade_denial(request, uid, raw["tier"])
            if tier_denial is not None:
                return tier_denial
    store: HistoryStore | None = getattr(request.app.state, "history_store", None)
    project_file_store: ProjectFileStore | None = request.app.state.project_file_store
    if browser_project_id is not None and uid is None:
        return JSONResponse({"error": {"code": "unauthorized", "message": "프로젝트를 사용하려면 로그인이 필요합니다."}}, status_code=401)

    effective_project_id = browser_project_id
    if uid is not None and store is not None and conversation_id is not None:
        try:
            existing_conversation = await store.get_conversation(
                uid, conversation_id, product_scope=PRODUCT_SCOPE_CHAT
            )
        except Exception:
            return _history_unavailable()
        if existing_conversation is None:
            return _conversation_not_found()
        stored_project_id = existing_conversation.get("project_id")
        if stored_project_id is not None and not isinstance(stored_project_id, str):
            return _conversation_not_found()
        if browser_project_id is not None and browser_project_id != stored_project_id:
            return _conversation_not_found()
        if browser_project_id is None:
            effective_project_id = stored_project_id
        try:
            messages = await _restore_owner_chat_model_messages(
                store, uid, conversation_id, existing_conversation, messages,
            )
        except HistoryContextIncomplete:
            return _model_history_incomplete()
        except OverflowError:
            return _model_history_too_large()
        except Exception:
            return _history_unavailable()

    project = None
    project_context = None
    project_files_context = None
    project_files_used = 0
    if effective_project_id is not None:
        if uid is None or store is None:
            return JSONResponse({"error": {"code": "unauthorized", "message": "프로젝트를 사용하려면 로그인이 필요합니다."}}, status_code=401)
        try:
            project = await store.get_project(uid, effective_project_id)
        except Exception:
            return _history_unavailable()
        if project is None:
            return _project_not_found()
        project_context = build_project_context(project)
        if project_file_store is not None:
            try:
                project_files = await project_file_store.list_files(uid, effective_project_id)
            except Exception:
                return _project_files_unavailable()
            project_files_context, project_files_used = build_project_files_context(project_files)

    image_attachments = tuple(item for item in attachments if isinstance(item, ImageAttachment))
    # #261102: every attached document reaches the model, each one introduced
    # by its own name through the shared multi-document builder.
    document_attachments = tuple(item for item in attachments if isinstance(item, DocumentAttachment))
    document_context = build_documents_context(document_attachments)
    reference_context = combine_reference_context(project_context, project_files_context, document_context)

    # PADIEM Custom: owner key -> explicitly selected provider model. The B14
    # client, router, registry, default/fallback policy and platform secret
    # store are not touched on this path.
    if custom is not None:
        try:
            custom_result = await _complete_custom_chat(
                request,
                uid=uid,
                selection=custom,
                messages=messages,
                reference_context=reference_context,
            )
        except CustomProviderSelectionError as exc:
            return _custom_selection_unsupported(exc)
        except CustomProviderError as exc:
            return _custom_error_response(exc)
        result = {"answer": custom_result["answer"]}
        latest_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), None)
        if latest_user:
            try:
                if effective_project_id is None:
                    saved_id = await store.append_exchange(
                        uid, conversation_id, latest_user, result["answer"],
                        product_scope=PRODUCT_SCOPE_CHAT,
                    )
                else:
                    saved_id = await store.append_exchange(
                        uid, conversation_id, latest_user, result["answer"],
                        project_id=effective_project_id,
                        product_scope=PRODUCT_SCOPE_CHAT,
                    )
            except HistoryForbidden:
                return _conversation_not_found()
            except Exception:
                saved_id = None
            if saved_id is not None:
                result["conversation_id"] = saved_id
                if effective_project_id is not None:
                    result["project_id"] = effective_project_id
        return JSONResponse(public_chat_result(result))

    latest_user_text = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    identity_question = is_padiem_identity_question(latest_user_text)

    async def _drive_preflight() -> tuple[str | None, tuple[dict[str, str], ...]]:
        if identity_question:
            return (None, ())
        return await drive_general_grounding(request, latest_user_text)

    async def _pc_preflight() -> str | None:
        if uid is None:
            return None
        from .pc_work_context import build_pc_work_context_text

        try:
            result = await build_pc_work_context_text(request, owner_id=uid)
        except Exception:
            return None
        return result if isinstance(result, str) else None

    drive_result, pc_work_result = await asyncio.gather(_drive_preflight(), _pc_preflight(), return_exceptions=True)

    if isinstance(drive_result, DriveGroundingError):
        return JSONResponse({"error": {"code": drive_result.code, "message": drive_result.message}}, status_code=drive_result.status_code)

    if isinstance(drive_result, BaseException):
        drive_result = (None, ())

    drive_context, drive_sources = drive_result if isinstance(drive_result, tuple) else (None, ())
    if drive_context:
        reference_context = (reference_context + "\n\n" if reference_context else "") + drive_context
    if isinstance(pc_work_result, str):
        reference_context = (
            reference_context + "\n\n" if reference_context else ""
        ) + pc_work_result

    if request.app.state.usage_gate_enforced:
        usage_gate: UsageGate = request.app.state.usage_gate
        usage_decision = await usage_gate.authorize(
            raw_ip=request.headers.get("cf-connecting-ip"),
            user_id=uid,
        )
        if not usage_decision.allowed:
            return _usage_denied_response(usage_decision)

    timezone_name = raw.get("timezone") if isinstance(raw.get("timezone"), str) else None
    calendar_store = getattr(request.app.state, "calendar_store", None)
    util_scope = declared_util_scope(raw)
    # An explicitly Google-named connector question ("구글 캘린더", "구글 드라이브")
    # belongs to the connector READ tools on this same turn, never to the
    # workspace-native calendar store.
    google_connector_turn = google_connector_intent(latest_user_text)
    needs_native_calendar = False
    if util_scope is None and not google_connector_turn:
        try:
            needs_native_calendar = parse_native_calendar_intent(latest_user_text, timezone_name=timezone_name)["op"] != "none"
        except Exception:
            needs_native_calendar = False
    if needs_native_calendar and calendar_store is None:
        return JSONResponse({"error": {"code": "calendar_store_unavailable", "message": "Calendar storage is unavailable"}}, status_code=503)
    if calendar_store is not None and util_scope is None and not google_connector_turn:
        try:
            client_turn_id = raw.get("calendar_turn_id")
            if not isinstance(client_turn_id, str):
                client_turn_id = request.headers.get("X-Padiem-Calendar-Turn-Id")
            if not isinstance(client_turn_id, str) or not client_turn_id or len(client_turn_id) > 128:
                client_turn_id = None
            material = "|" + client_turn_id if client_turn_id is not None else ""
            turn_key = "chat-" + str(uid) + "-" + str(conversation_id or "anon") + "-" + str(len(messages)) + "-" + (__import__("hashlib").sha256("|".join((str(latest_user_text), str(timezone_name or ""), material)).encode("utf-8")).hexdigest()[:16])
            native_result = await try_native_calendar_chat(request, calendar_store, uid, messages, timezone_name=timezone_name, turn_key=turn_key)
        except NativeCalendarAdapterError as exc:
            return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status_code)
        except Exception:
            native_result = None
        if needs_native_calendar and native_result is None:
            return JSONResponse({"error": {"code": "calendar_unavailable", "message": "native calendar unavailable"}}, status_code=503)
        if native_result is not None:
            answer = native_result.get("answer", "")
            result = {"answer": answer}
            if native_result.get("native_calendar") is not None:
                result["native_calendar"] = native_result["native_calendar"]
            if uid is not None and store is not None and latest_user_text:
                try:
                    saved_id = await store.append_exchange(uid, conversation_id, latest_user_text, answer, product_scope=PRODUCT_SCOPE_CHAT)
                except Exception:
                    saved_id = None
            else:
                saved_id = None
            if saved_id is not None:
                result["conversation_id"] = saved_id
            return JSONResponse(public_chat_result(result))

    try:
        async with chat_request_tier_context(request, raw.get("tier", "free")):
            if tool_request is None:
                auto_grounding: AutoGroundingService = request.app.state.auto_grounding
                auto_decision = None if image_attachments or drive_context or identity_question else auto_grounding.decide(
                    messages,
                    skill=skill,
                    util_scope=util_scope,
                    **({"explicit_search": True} if raw.get("web_search") else {}),
                )

                async def _plain_completion() -> dict[str, Any]:
                    client: B14Client = request.app.state.b14_client
                    policy = resolve_request_model_policy(messages)
                    guard = await create_guard_from_request(
                        request,
                        policy.model_id,
                        request.app.state.central_model_policy_store,
                        request.app.state.b14_catalog_source,
                    )
                    client = apply_guard_to_client(client, guard)
                    return await client.complete(
                        messages,
                        skill=skill,
                        additional_system_context=reference_context,
                        attachments=image_attachments,
                    )

                if auto_decision is not None and auto_decision.requires_search:
                    grounded: GroundedChatService = request.app.state.grounded_chat
                    try:
                        result = await grounded.complete(
                            messages,
                            skill=skill,
                            tool=get_tool_presentation("web_search"),
                            tool_input=auto_decision.query,
                            additional_system_context=reference_context,
                        )
                    except GroundingError as exc:
                        if not auto_grounding_may_continue(auto_decision, exc):
                            raise
                        # Owner 2026-10-24: failed retrieval is disclosed;
                        # the same selected model answers without web sources.
                        result = await _plain_completion()
                        result.update(grounding_fallback_fields(exc))
                else:
                    result = await _plain_completion()
                    # #6090: an automatic search skipped because the request is a
                    # document says so in Korean; a plain long answer says nothing.
                    if auto_decision is not None:
                        result.update(auto_grounding_skip_fields(auto_decision))
            else:
                grounded = request.app.state.grounded_chat
                result = await grounded.complete(
                    messages,
                    skill=skill,
                    tool=tool_request.tool,
                    tool_input=tool_request.tool_input,
                    additional_system_context=reference_context,
                )

    except (ChatRuntimeError, GroundingError, WebToolError) as exc:
        return JSONResponse({"error": {"code": exc.code, "message": exc.user_message}}, status_code=exc.status_code)

    if drive_sources:
        result["evidence"] = [
            {"id": f"drive-{i}", "title": src["title"], "url": src["url"],
             "retrieved_at": src["retrieved_at"], "source_type": "google_drive"}
            for i, src in enumerate(drive_sources, 1)
        ]
    if document_attachments:
        result["attachments"] = [item.public_dict() for item in document_attachments]
    if project_files_used:
        result["project_files_used"] = project_files_used

    if uid is not None and store is not None:
        latest_user = next((item["content"] for item in reversed(messages) if item["role"] == "user"), None)
        if latest_user:
            try:
                if effective_project_id is None:
                    saved_id = await store.append_exchange(uid, conversation_id, latest_user, result["answer"], product_scope=PRODUCT_SCOPE_CHAT)
                else:
                    saved_id = await store.append_exchange(
                        uid, conversation_id, latest_user, result["answer"], project_id=effective_project_id,
                        product_scope=PRODUCT_SCOPE_CHAT,
                    )
            except HistoryForbidden:
                return _conversation_not_found()
            except Exception:
                saved_id = None
            if saved_id is not None:
                result["conversation_id"] = saved_id
                if effective_project_id is not None:
                    result["project_id"] = effective_project_id
                    result["project"] = {"id": project.id, "name": project.name} if project is not None else None
    return JSONResponse(public_chat_result(result))
