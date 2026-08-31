from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .attachments import AttachmentValidationError, ImageAttachment, parse_attachments
from .auth import GoogleOAuthClient
from .auth_routes import auth_ready, auth_status, current_user_id, google_callback, google_start, logout
from .b14_client import B14Client, ChatRuntimeError
from .config import ConfigError, Settings
from .documents import (
    DocumentAttachment,
    build_document_context,
    build_project_files_context,
    combine_reference_context,
)
from .grounding import GroundedChatService, GroundingError
from .history import (
    HistoryForbidden,
    HistoryStore,
    build_project_context,
    validate_conversation_id,
    validate_project_id,
)
from .model_policy import ModelPolicyError, model_supports, resolve_model_policy
from .project_file_routes import project_file_detail, project_files_collection
from .project_files import ProjectFileStore
from .project_routes import project_detail, projects_collection
from .public_chat import public_chat_result
from .saved_output_routes import output_detail, outputs_collection
from .saved_outputs import SavedOutputStore
from .task_modes import TaskMode, get_task_mode
from .tool_presentations import ToolPresentationDescriptor, get_tool_presentation
from .usage_gate import UsageCounterStore, UsageGate
from .web_tools import MAX_QUERY_CHARS, WebToolError, create_web_provider, normalize_public_url

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
MAX_BROWSER_BODY_BYTES = 6_000_000
MAX_MESSAGES = 20
MAX_MESSAGE_CHARS = 8_000
MAX_TOTAL_MESSAGE_CHARS = 32_000
_ALLOWED_ROLES = {"user", "assistant"}


class BrowserRequestError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class BrowserToolRequest:
    tool: ToolPresentationDescriptor
    tool_input: str | None


def _validate_tool_request(raw: dict[str, Any]) -> BrowserToolRequest | None:
    tool_value = raw.get("tool")
    has_tool_input = "tool_input" in raw
    if tool_value is None:
        if has_tool_input:
            raise BrowserRequestError("도구 입력을 사용하려면 도구를 함께 선택해 주세요.")
        return None
    if not isinstance(tool_value, str) or not tool_value.strip():
        raise BrowserRequestError("도구 형식이 올바르지 않습니다.")
    try:
        tool = get_tool_presentation(tool_value.strip())
    except ValueError as exc:
        raise BrowserRequestError(str(exc)) from exc

    value = raw.get("tool_input")
    if tool.id in {"web_search", "deep_research"}:
        if value is None:
            return BrowserToolRequest(tool=tool, tool_input=None)
        if not isinstance(value, str):
            raise BrowserRequestError("검색어 형식이 올바르지 않습니다.")
        query = value.strip()
        if not query or len(query) > MAX_QUERY_CHARS:
            raise BrowserRequestError("검색어는 1자 이상 2000자 이하로 입력해 주세요.")
        return BrowserToolRequest(tool=tool, tool_input=query)
    if tool.id == "web_fetch":
        if not isinstance(value, str) or not value.strip():
            raise BrowserRequestError("읽을 공개 웹 주소가 필요합니다.")
        try:
            safe_url = normalize_public_url(value)
        except ValueError as exc:
            raise BrowserRequestError(str(exc)) from exc
        return BrowserToolRequest(tool=tool, tool_input=safe_url)
    raise BrowserRequestError("지원하지 않는 도구입니다.")


def _validate_payload(
    raw: Any,
) -> tuple[list[dict[str, str]], TaskMode, BrowserToolRequest | None, tuple[Any, ...], str | None, str | None]:
    if not isinstance(raw, dict):
        raise BrowserRequestError("요청 형식이 올바르지 않습니다.")
    if set(raw) - {"messages", "mode", "skill", "tool", "tool_input", "attachments", "conversation_id", "project_id"}:
        raise BrowserRequestError("지원하지 않는 요청 항목이 있습니다.")
    if raw.get("mode", "auto") != "auto":
        raise BrowserRequestError("현재는 자동 추천 모드만 지원합니다.")

    skill_id = raw.get("skill", "auto")
    if not isinstance(skill_id, str) or not skill_id.strip():
        raise BrowserRequestError("작업 모드 형식이 올바르지 않습니다.")
    try:
        skill = get_task_mode(skill_id.strip())
    except ValueError as exc:
        raise BrowserRequestError(str(exc)) from exc

    messages = raw.get("messages")
    if not isinstance(messages, list) or not 1 <= len(messages) <= MAX_MESSAGES:
        raise BrowserRequestError("대화 내용은 1개 이상 20개 이하로 보내 주세요.")
    out: list[dict[str, str]] = []
    total = 0
    for item in messages:
        if not isinstance(item, dict) or set(item) != {"role", "content"}:
            raise BrowserRequestError("대화 항목 형식이 올바르지 않습니다.")
        role = item.get("role")
        content = item.get("content")
        if role not in _ALLOWED_ROLES:
            raise BrowserRequestError("브라우저에서는 사용자와 AI 대화만 보낼 수 있습니다.")
        if not isinstance(content, str) or not content.strip():
            raise BrowserRequestError("빈 메시지는 보낼 수 없습니다.")
        text = content.strip()
        if len(text) > MAX_MESSAGE_CHARS:
            raise BrowserRequestError("한 메시지가 너무 깁니다.")
        total += len(text)
        if total > MAX_TOTAL_MESSAGE_CHARS:
            raise BrowserRequestError("한 번에 보낸 대화가 너무 깁니다.")
        out.append({"role": role, "content": text})
    if not any(item["role"] == "user" for item in out):
        raise BrowserRequestError("사용자 질문이 필요합니다.")

    tool_request = _validate_tool_request(raw)
    try:
        attachments = parse_attachments(raw.get("attachments"))
    except AttachmentValidationError as exc:
        raise BrowserRequestError(str(exc)) from exc
    if tool_request is not None and any(isinstance(item, ImageAttachment) for item in attachments):
        raise BrowserRequestError("현재는 사진 첨부와 웹 도구를 한 요청에서 함께 사용할 수 없습니다.")
    try:
        conversation_id = validate_conversation_id(raw.get("conversation_id"))
        project_id = validate_project_id(raw.get("project_id"))
    except ValueError as exc:
        raise BrowserRequestError(str(exc)) from exc
    return out, skill, tool_request, attachments, conversation_id, project_id


def _apply_b62_model_policy(messages: list[dict[str, str]]) -> tuple[str, list[dict[str, str]]]:
    try:
        policy = resolve_model_policy(messages)
    except ModelPolicyError as exc:
        raise BrowserRequestError(exc.message) from exc
    return policy.model_id, policy.messages


async def health(request: Request) -> JSONResponse:
    settings: Settings = request.app.state.settings
    usage_gate: UsageGate = request.app.state.usage_gate
    web_ready = settings.web_provider in {"mock", "firecrawl"}
    abuse_ready = usage_gate.ready
    return JSONResponse({
        "status": "ok", "app": "padiem-chat", "runtime": settings.runtime_mode,
        "b14_configured": bool(settings.b14_base_url),
        "web_tools_ready": web_ready,
        "deep_research_ready": settings.runtime_mode == "b14" and web_ready,
        "image_attachment_ready": True,
        "text_document_attachment_ready": True,
        "auth_configured": settings.auth_mode == "google",
        "history_store_bound": request.app.state.history_store is not None,
        "projects_code_ready": True,
        "project_files_code_ready": True,
        "project_file_store_bound": request.app.state.project_file_store is not None,
        "saved_outputs_code_ready": True,
        "saved_output_store_bound": request.app.state.saved_output_store is not None,
        "quota_store_bound": usage_gate.quota_store_bound,
        "live_abuse_gate_ready": abuse_ready,
        "live_enabled": settings.runtime_mode == "b14" and abuse_ready,
    })


def _too_large_response() -> JSONResponse:
    return JSONResponse({"error": {"code": "request_too_large", "message": "요청이 너무 큽니다."}}, status_code=413)


def _history_unavailable() -> JSONResponse:
    return JSONResponse({"error": {"code": "history_unavailable", "message": "저장된 대화를 현재 사용할 수 없습니다."}}, status_code=503)


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


async def api_conversations(request: Request) -> JSONResponse:
    if not auth_ready(request):
        return _history_unavailable()
    uid = current_user_id(request)
    if uid is None:
        return JSONResponse({"error": {"code": "unauthorized", "message": "로그인이 필요합니다."}}, status_code=401)
    store: HistoryStore = request.app.state.history_store
    try:
        conversations = await store.list_conversations(uid)
    except Exception:
        return _history_unavailable()
    return JSONResponse({"conversations": conversations})


async def api_conversation_detail(request: Request) -> JSONResponse:
    if not auth_ready(request):
        return _history_unavailable()
    uid = current_user_id(request)
    if uid is None:
        return JSONResponse({"error": {"code": "unauthorized", "message": "로그인이 필요합니다."}}, status_code=401)
    try:
        cid = validate_conversation_id(request.path_params.get("conversation_id"))
    except ValueError:
        cid = None
    if cid is None:
        return JSONResponse({"error": {"code": "not_found", "message": "대화를 찾을 수 없습니다."}}, status_code=404)
    store: HistoryStore = request.app.state.history_store
    if request.method == "DELETE":
        try:
            deleted = await store.delete_conversation(uid, cid)
        except Exception:
            return _history_unavailable()
        if not deleted:
            return JSONResponse({"error": {"code": "not_found", "message": "대화를 찾을 수 없습니다."}}, status_code=404)
        return JSONResponse({"deleted": True, "conversation_id": cid})
    try:
        conversation = await store.get_conversation(uid, cid)
    except Exception:
        return _history_unavailable()
    if conversation is None:
        return JSONResponse({"error": {"code": "not_found", "message": "대화를 찾을 수 없습니다."}}, status_code=404)
    return JSONResponse({"conversation": conversation})


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
            client: B14Client = request.app.state.b14_client
            result = await client.complete(
                messages,
                skill=skill,
                additional_system_context=reference_context,
                attachments=image_attachments,
            )
        else:
            grounded: GroundedChatService = request.app.state.grounded_chat
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


def create_app(
    settings: Settings | None = None,
    transport=None,
    web_transport=None,
    auth_transport=None,
    history_store: HistoryStore | None = None,
    project_file_store: ProjectFileStore | None = None,
    saved_output_store: SavedOutputStore | None = None,
    usage_store: UsageCounterStore | None = None,
) -> Starlette:
    resolved = settings or Settings.from_env()
    routes = [
        Route("/health", health, methods=["GET"]),
        Route("/api/auth/status", auth_status, methods=["GET"]),
        Route("/auth/google/start", google_start, methods=["GET"]),
        Route("/auth/google/callback", google_callback, methods=["GET"]),
        Route("/api/auth/logout", logout, methods=["POST"]),
        Route("/api/projects", projects_collection, methods=["GET", "POST"]),
        Route("/api/projects/{project_id}", project_detail, methods=["GET", "PATCH", "DELETE"]),
        Route("/api/projects/{project_id}/files", project_files_collection, methods=["GET", "POST"]),
        Route("/api/projects/{project_id}/files/{file_id}", project_file_detail, methods=["GET", "DELETE"]),
        Route("/api/outputs", outputs_collection, methods=["GET", "POST"]),
        Route("/api/outputs/{output_id}", output_detail, methods=["GET", "PATCH", "DELETE"]),
        Route("/api/conversations", api_conversations, methods=["GET"]),
        Route("/api/conversations/{conversation_id}", api_conversation_detail, methods=["GET", "DELETE"]),
        Route("/api/chat/stream", api_chat_stream, methods=["POST"]),
        Route("/api/chat", api_chat, methods=["POST"]),
        Mount("/", app=StaticFiles(directory=str(STATIC_DIR), html=True), name="static"),
    ]
    app = Starlette(routes=routes)
    app.state.settings = resolved
    app.state.history_store = history_store
    app.state.project_file_store = project_file_store
    app.state.saved_output_store = saved_output_store
    app.state.usage_gate = UsageGate(resolved, usage_store)
    # An explicitly injected B14 transport is the existing network-free regression seam.
    # It cannot occur through browser input or Worker bindings. Production/ordinary runtime
    # (transport=None) always enforces the gate; quota-specific integration tests also
    # enforce it by supplying a usage store.
    app.state.usage_gate_enforced = not (transport is not None and usage_store is None)
    app.state.google_oauth = GoogleOAuthClient(resolved, transport=auth_transport)
    app.state.b14_client = B14Client(resolved, transport=transport)
    app.state.web_provider = create_web_provider(resolved, transport=web_transport)
    app.state.grounded_chat = GroundedChatService(app.state.b14_client, app.state.web_provider)
    return app


try:
    app = create_app()
except ConfigError as exc:
    raise RuntimeError(f"Padiem Chat configuration error: {exc}") from exc