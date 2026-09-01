from __future__ import annotations

import asyncio
import json
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

from .attachments import ImageAttachment
from .auth_routes import auth_ready, current_user_id
from .auto_grounding import AutoGroundingService
from .b14_client import B14Client, ChatRuntimeError
from .config import Settings
from .conversation_routes import _history_unavailable
from .documents import (
    DocumentAttachment,
    build_document_context,
    build_project_files_context,
    combine_reference_context,
)
from .grounding import GroundedChatService, GroundingError
from .history import HistoryForbidden, HistoryStore, build_project_context
from .model_policy import model_supports
from .project_files import ProjectFileStore
from .public_chat import public_chat_result
from .request_contract import (
    MAX_BROWSER_BODY_BYTES,
    BrowserRequestError,
    _apply_b62_model_policy,
    _validate_payload,
)
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


def _public_sse(event: str, payload: dict[str, Any]) -> bytes:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {data}\n\n".encode("utf-8")


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


async def _close_stream(stream: Any) -> None:
    closer = getattr(stream, "aclose", None)
    if callable(closer):
        try:
            await closer()
        except Exception:
            pass


async def api_chat_stream(request: Request):
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_BROWSER_BODY_BYTES:
                return _too_large_response()
        except ValueError:
            return JSONResponse({"error": {"code": "invalid_request", "message": "요청 형식이 올바르지 않습니다."}}, status_code=422)
    body = await request.body()
    if len(body) > MAX_BROWSER_BODY_BYTES:
        return _too_large_response()

    try:
        raw = json.loads(body.decode("utf-8"))
        messages, skill, tool_request, attachments, conversation_id, browser_project_id = _validate_payload(raw)
        _, messages = _apply_b62_model_policy(messages)
    except (UnicodeDecodeError, json.JSONDecodeError, BrowserRequestError) as exc:
        message = str(exc) if isinstance(exc, BrowserRequestError) else "요청 형식이 올바르지 않습니다."
        return JSONResponse({"error": {"code": "invalid_request", "message": message}}, status_code=422)

    if tool_request is not None or attachments:
        return JSONResponse(
            {"error": {"code": "streaming_unsupported", "message": "스트리밍 채팅은 현재 일반 텍스트 질문만 지원합니다."}},
            status_code=422,
        )

    uid = current_user_id(request) if auth_ready(request) else None
    store: HistoryStore | None = request.app.state.history_store
    project_file_store: ProjectFileStore | None = request.app.state.project_file_store
    if browser_project_id is not None and uid is None:
        return JSONResponse({"error": {"code": "unauthorized", "message": "프로젝트를 사용하려면 로그인이 필요합니다."}}, status_code=401)

    effective_project_id = browser_project_id
    if uid is not None and store is not None and conversation_id is not None:
        try:
            existing_conversation = await store.get_conversation(uid, conversation_id)
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

    reference_context = combine_reference_context(project_context, project_files_context, None)

    if request.app.state.usage_gate_enforced:
        usage_gate: UsageGate = request.app.state.usage_gate
        usage_decision = await usage_gate.authorize(
            raw_ip=request.headers.get("cf-connecting-ip"),
            user_id=uid,
        )
        if not usage_decision.allowed:
            return _usage_denied_response(usage_decision)

    auto_grounding: AutoGroundingService = request.app.state.auto_grounding
    try:
        auto_plan = await auto_grounding.prepare(
            messages,
            skill=skill,
            additional_system_context=reference_context,
        )
    except GroundingError as exc:
        return JSONResponse({"error": {"code": exc.code, "message": exc.user_message}}, status_code=exc.status_code)
    if auto_plan.prepared is not None:
        reference_context = auto_plan.prepared.context

    client: B14Client = request.app.state.b14_client
    stream = client.stream_text_auto(
        messages,
        skill=skill,
        additional_system_context=reference_context,
    )

    first_visible = None
    try:
        while True:
            try:
                event = await anext(stream)
            except StopAsyncIteration:
                await _close_stream(stream)
                return _empty_stream_json_error()
            if event.delta_content:
                first_visible = event
                break
            if event.done:
                await _close_stream(stream)
                return _empty_stream_json_error()
    except ChatRuntimeError as exc:
        await _close_stream(stream)
        return _stream_json_error(exc)
    except asyncio.CancelledError:
        await _close_stream(stream)
        raise
    except Exception:
        await _close_stream(stream)
        return JSONResponse(
            {"error": {"code": "upstream_error", "message": "답변을 불러오지 못했습니다. 다시 시도해 주세요."}},
            status_code=502,
        )

    assert first_visible is not None and first_visible.delta_content
    first_delta = first_visible.delta_content
    latest_user = next((item["content"] for item in reversed(messages) if item["role"] == "user"), None)

    async def body_iterator():
        answer_parts = [first_delta]
        try:
            yield _public_sse("delta", {"delta": first_delta})
            async for event in stream:
                if event.delta_content:
                    answer_parts.append(event.delta_content)
                    yield _public_sse("delta", {"delta": event.delta_content})
                if event.done:
                    done_payload: dict[str, Any] = {"done": True}
                    if auto_plan.prepared is not None:
                        done_payload["answer_status"] = "answered_with_evidence"
                        done_payload["evidence"] = _public_evidence(auto_plan.prepared.evidence)
                        done_payload["tool"] = {"id": "web_search", "title": "웹 검색"}
                    if uid is not None and store is not None and latest_user:
                        answer = "".join(answer_parts)
                        try:
                            if effective_project_id is None:
                                saved_id = await store.append_exchange(uid, conversation_id, latest_user, answer)
                            else:
                                saved_id = await store.append_exchange(
                                    uid,
                                    conversation_id,
                                    latest_user,
                                    answer,
                                    project_id=effective_project_id,
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
            yield _public_sse(
                "error",
                {"error": {"code": exc.code, "message": exc.user_message}},
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            yield _public_sse(
                "error",
                {"error": {"code": "stream_error", "message": "스트리밍 답변을 계속하지 못했습니다. 다시 시도해 주세요."}},
            )
        finally:
            await _close_stream(stream)

    return StreamingResponse(
        body_iterator(),
        status_code=200,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",
        },
    )


async def api_chat(request: Request) -> JSONResponse:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_BROWSER_BODY_BYTES:
                return _too_large_response()
        except ValueError:
            return JSONResponse({"error": {"code": "invalid_request", "message": "요청 형식이 올바르지 않습니다."}}, status_code=422)
    body = await request.body()
    if len(body) > MAX_BROWSER_BODY_BYTES:
        return _too_large_response()

    try:
        raw = json.loads(body.decode("utf-8"))
        messages, skill, tool_request, attachments, conversation_id, browser_project_id = _validate_payload(raw)
        selected_model, messages = _apply_b62_model_policy(messages)
    except (UnicodeDecodeError, json.JSONDecodeError, BrowserRequestError) as exc:
        message = str(exc) if isinstance(exc, BrowserRequestError) else "요청 형식이 올바르지 않습니다."
        return JSONResponse({"error": {"code": "invalid_request", "message": message}}, status_code=422)

    settings: Settings = request.app.state.settings
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
    store: HistoryStore | None = request.app.state.history_store
    project_file_store: ProjectFileStore | None = request.app.state.project_file_store
    if browser_project_id is not None and uid is None:
        return JSONResponse({"error": {"code": "unauthorized", "message": "프로젝트를 사용하려면 로그인이 필요합니다."}}, status_code=401)

    effective_project_id = browser_project_id
    if uid is not None and store is not None and conversation_id is not None:
        try:
            existing_conversation = await store.get_conversation(uid, conversation_id)
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
    document_attachment = next((item for item in attachments if isinstance(item, DocumentAttachment)), None)
    document_context = build_document_context(document_attachment) if document_attachment is not None else None
    reference_context = combine_reference_context(project_context, project_files_context, document_context)

    if request.app.state.usage_gate_enforced:
        usage_gate: UsageGate = request.app.state.usage_gate
        usage_decision = await usage_gate.authorize(
            raw_ip=request.headers.get("cf-connecting-ip"),
            user_id=uid,
        )
        if not usage_decision.allowed:
            return _usage_denied_response(usage_decision)

    try:
        if tool_request is None:
            auto_grounding: AutoGroundingService = request.app.state.auto_grounding
            auto_decision = None if image_attachments else auto_grounding.decide(messages, skill=skill)
            if auto_decision is not None and auto_decision.requires_search:
                grounded: GroundedChatService = request.app.state.grounded_chat
                result = await grounded.complete(
                    messages,
                    skill=skill,
                    tool=get_tool_presentation("web_search"),
                    tool_input=auto_decision.query,
                    additional_system_context=reference_context,
                )
            else:
                client: B14Client = request.app.state.b14_client
                result = await client.complete(
                    messages,
                    skill=skill,
                    additional_system_context=reference_context,
                    attachments=image_attachments,
                )
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

    if document_attachment is not None:
        result["attachments"] = [document_attachment.public_dict()]
    if project_files_used:
        result["project_files_used"] = project_files_used

    if uid is not None and store is not None:
        latest_user = next((item["content"] for item in reversed(messages) if item["role"] == "user"), None)
        if latest_user:
            try:
                if effective_project_id is None:
                    saved_id = await store.append_exchange(uid, conversation_id, latest_user, result["answer"])
                else:
                    saved_id = await store.append_exchange(
                        uid, conversation_id, latest_user, result["answer"], project_id=effective_project_id
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
