from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
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
from .project_file_routes import project_file_detail, project_files_collection
from .project_files import ProjectFileStore
from .project_routes import project_detail, projects_collection
from .saved_output_routes import output_detail, outputs_collection
from .saved_outputs import SavedOutputStore
from .skills import Skill, get_skill
from .tools import ToolSpec, get_tool
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
    tool: ToolSpec
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
        tool = get_tool(tool_value.strip())
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
) -> tuple[list[dict[str, str]], Skill, BrowserToolRequest | None, tuple[Any, ...], str | None, str | None]:
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
        skill = get_skill(skill_id.strip())
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


async def health(request: Request) -> JSONResponse:
    settings: Settings = request.app.state.settings
    web_ready = settings.web_provider in {"mock", "firecrawl"}
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
    try:
        conversation = await store.get_conversation(uid, cid)
    except Exception:
        return _history_unavailable()
    if conversation is None:
        return JSONResponse({"error": {"code": "not_found", "message": "대화를 찾을 수 없습니다."}}, status_code=404)
    return JSONResponse({"conversation": conversation})


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
    except (UnicodeDecodeError, json.JSONDecodeError, BrowserRequestError) as exc:
        message = str(exc) if isinstance(exc, BrowserRequestError) else "요청 형식이 올바르지 않습니다."
        return JSONResponse({"error": {"code": "invalid_request", "message": message}}, status_code=422)

    settings: Settings = request.app.state.settings
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
    return JSONResponse(result)


def create_app(
    settings: Settings | None = None,
    transport=None,
    web_transport=None,
    auth_transport=None,
    history_store: HistoryStore | None = None,
    project_file_store: ProjectFileStore | None = None,
    saved_output_store: SavedOutputStore | None = None,
) -> Starlette:
    resolved = settings or Settings.from_env()
    routes = [
        Route("/health", health, methods=["GET"]),
        Route("/api/auth/status", auth_status, methods=["GET"]),
        Route("/auth/google/start", google_start, methods=["GET"]),
        Route("/auth/google/callback", google_callback, methods=["GET"]),
        Route("/api/auth/logout", logout, methods=["POST"]),
        Route("/api/projects", projects_collection, methods=["GET", "POST"]),
        Route("/api/projects/{project_id}", project_detail, methods=["GET", "PATCH"]),
        Route("/api/projects/{project_id}/files", project_files_collection, methods=["GET", "POST"]),
        Route("/api/projects/{project_id}/files/{file_id}", project_file_detail, methods=["GET", "DELETE"]),
        Route("/api/outputs", outputs_collection, methods=["GET", "POST"]),
        Route("/api/outputs/{output_id}", output_detail, methods=["GET", "PATCH", "DELETE"]),
        Route("/api/conversations", api_conversations, methods=["GET"]),
        Route("/api/conversations/{conversation_id}", api_conversation_detail, methods=["GET"]),
        Route("/api/chat", api_chat, methods=["POST"]),
        Mount("/", app=StaticFiles(directory=str(STATIC_DIR), html=True), name="static"),
    ]
    app = Starlette(routes=routes)
    app.state.settings = resolved
    app.state.history_store = history_store
    app.state.project_file_store = project_file_store
    app.state.saved_output_store = saved_output_store
    app.state.google_oauth = GoogleOAuthClient(resolved, transport=auth_transport)
    app.state.b14_client = B14Client(resolved, transport=transport)
    app.state.web_provider = create_web_provider(resolved, transport=web_transport)
    app.state.grounded_chat = GroundedChatService(app.state.b14_client, app.state.web_provider)
    return app


try:
    app = create_app()
except ConfigError as exc:
    raise RuntimeError(f"Padiem Chat configuration error: {exc}") from exc
