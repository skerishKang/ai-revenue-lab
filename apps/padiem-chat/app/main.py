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
from .b14_client import B14Client, ChatRuntimeError
from .config import ConfigError, Settings
from .grounding import GroundedChatService, GroundingError
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
    if tool.id == "web_search":
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
) -> tuple[
    list[dict[str, str]],
    Skill,
    BrowserToolRequest | None,
    tuple[ImageAttachment, ...],
]:
    if not isinstance(raw, dict):
        raise BrowserRequestError("요청 형식이 올바르지 않습니다.")
    if set(raw) - {"messages", "mode", "skill", "tool", "tool_input", "attachments"}:
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
    if tool_request is not None and attachments:
        raise BrowserRequestError("현재는 사진 첨부와 웹 도구를 한 요청에서 함께 사용할 수 없습니다.")

    return out, skill, tool_request, attachments


async def health(request: Request) -> JSONResponse:
    settings: Settings = request.app.state.settings
    return JSONResponse({
        "status": "ok",
        "app": "padiem-chat",
        "runtime": settings.runtime_mode,
        "b14_configured": bool(settings.b14_base_url),
        "web_tools_ready": settings.web_provider in {"mock", "firecrawl"},
        "image_attachment_ready": True,
    })


def _too_large_response() -> JSONResponse:
    return JSONResponse(
        {"error": {"code": "request_too_large", "message": "요청이 너무 큽니다."}},
        status_code=413,
    )


async def api_chat(request: Request) -> JSONResponse:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_BROWSER_BODY_BYTES:
                return _too_large_response()
        except ValueError:
            return JSONResponse(
                {"error": {"code": "invalid_request", "message": "요청 형식이 올바르지 않습니다."}},
                status_code=422,
            )

    body = await request.body()
    if len(body) > MAX_BROWSER_BODY_BYTES:
        return _too_large_response()

    try:
        raw = json.loads(body.decode("utf-8"))
        messages, skill, tool_request, attachments = _validate_payload(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, BrowserRequestError) as exc:
        message = str(exc) if isinstance(exc, BrowserRequestError) else "요청 형식이 올바르지 않습니다."
        return JSONResponse(
            {"error": {"code": "invalid_request", "message": message}},
            status_code=422,
        )

    try:
        if tool_request is None:
            client: B14Client = request.app.state.b14_client
            result = await client.complete(messages, skill=skill, attachments=attachments)
        else:
            grounded: GroundedChatService = request.app.state.grounded_chat
            result = await grounded.complete(
                messages,
                skill=skill,
                tool=tool_request.tool,
                tool_input=tool_request.tool_input,
            )
    except (ChatRuntimeError, GroundingError, WebToolError) as exc:
        return JSONResponse(
            {"error": {"code": exc.code, "message": exc.user_message}},
            status_code=exc.status_code,
        )

    return JSONResponse(result)


def create_app(
    settings: Settings | None = None,
    transport=None,
    web_transport=None,
) -> Starlette:
    resolved = settings or Settings.from_env()
    routes = [
        Route("/health", health, methods=["GET"]),
        Route("/api/chat", api_chat, methods=["POST"]),
        Mount("/", app=StaticFiles(directory=str(STATIC_DIR), html=True), name="static"),
    ]
    app = Starlette(routes=routes)
    app.state.settings = resolved
    app.state.b14_client = B14Client(resolved, transport=transport)
    app.state.web_provider = create_web_provider(resolved, transport=web_transport)
    app.state.grounded_chat = GroundedChatService(app.state.b14_client, app.state.web_provider)
    return app


try:
    app = create_app()
except ConfigError as exc:
    raise RuntimeError(f"Padiem Chat configuration error: {exc}") from exc
