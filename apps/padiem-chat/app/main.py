from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .b14_client import B14Client, ChatRuntimeError
from .config import ConfigError, Settings
from .skills import Skill, get_skill
from .web_tools import create_web_provider

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
MAX_BROWSER_BODY_BYTES = 65_536
MAX_MESSAGES = 20
MAX_MESSAGE_CHARS = 8_000
MAX_TOTAL_MESSAGE_CHARS = 32_000
_ALLOWED_ROLES = {"user", "assistant"}


class BrowserRequestError(ValueError):
    pass


def _validate_payload(raw: Any) -> tuple[list[dict[str, str]], Skill]:
    if not isinstance(raw, dict):
        raise BrowserRequestError("요청 형식이 올바르지 않습니다.")
    if set(raw) - {"messages", "mode", "skill"}:
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
    return out, skill


async def health(request: Request) -> JSONResponse:
    settings: Settings = request.app.state.settings
    return JSONResponse({
        "status": "ok",
        "app": "padiem-chat",
        "runtime": settings.runtime_mode,
        "b14_configured": bool(settings.b14_base_url),
        "web_tools_ready": settings.web_provider in {"mock", "firecrawl"},
    })


async def api_chat(request: Request) -> JSONResponse:
    body = await request.body()
    if len(body) > MAX_BROWSER_BODY_BYTES:
        return JSONResponse(
            {"error": {"code": "request_too_large", "message": "요청이 너무 큽니다."}},
            status_code=413,
        )

    try:
        raw = json.loads(body.decode("utf-8"))
        messages, skill = _validate_payload(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, BrowserRequestError) as exc:
        message = str(exc) if isinstance(exc, BrowserRequestError) else "요청 형식이 올바르지 않습니다."
        return JSONResponse(
            {"error": {"code": "invalid_request", "message": message}},
            status_code=422,
        )

    client: B14Client = request.app.state.b14_client
    try:
        result = await client.complete(messages, skill=skill)
    except ChatRuntimeError as exc:
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
    return app


try:
    app = create_app()
except ConfigError as exc:
    raise RuntimeError(f"Padiem Chat configuration error: {exc}") from exc
