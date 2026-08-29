from __future__ import annotations

import json
from http.cookies import SimpleCookie
from typing import Any

from starlette.responses import JSONResponse

from .auth import SESSION_COOKIE, decode_session_token
from .history import validate_conversation_id
from .model_policy import (
    ModelPolicyError,
    reset_request_profile,
    set_request_profile,
    validate_public_profile_selection,
)

MAX_GUARD_BODY_BYTES = 6_000_000
_CHAT_PATHS = {"/api/chat", "/api/chat/stream"}


def _headers(scope: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw_name, raw_value in scope.get("headers", []):
        try:
            name = bytes(raw_name).decode("latin-1").lower()
            value = bytes(raw_value).decode("latin-1")
        except Exception:
            continue
        out[name] = value
    return out


def _cookie_value(scope: dict[str, Any], name: str) -> str | None:
    raw_cookie = _headers(scope).get("cookie")
    if not raw_cookie:
        return None
    cookie = SimpleCookie()
    try:
        cookie.load(raw_cookie)
    except Exception:
        return None
    morsel = cookie.get(name)
    return morsel.value if morsel is not None else None


def _error(code: str, message: str, *, status_code: int = 422) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message}},
        status_code=status_code,
        headers={"Cache-Control": "no-store"},
    )


async def _stored_conversation_uses_project(app: Any, scope: dict[str, Any], raw: dict[str, Any]) -> bool:
    conversation_id = raw.get("conversation_id")
    if conversation_id is None:
        return False
    try:
        cid = validate_conversation_id(conversation_id)
    except ValueError:
        return False
    if cid is None:
        return False

    store = getattr(app.state, "history_store", None)
    settings = getattr(app.state, "settings", None)
    if store is None or settings is None:
        return False

    session = _cookie_value(scope, SESSION_COOKIE)
    uid = decode_session_token(settings, session)
    if uid is None:
        return False

    try:
        conversation = await store.get_conversation(uid, cid)
    except Exception as exc:
        raise RuntimeError("high context check unavailable") from exc
    if conversation is None:
        return False
    return conversation.get("project_id") is not None


class ProfileGuard:
    """Request-scoped public model selection and HIGH fail-closed safety gate.

    The browser only supplies a product profile assertion. This guard validates
    that assertion before the existing Starlette app runs, binds it to a
    ContextVar for the B62/Core model policy, and blocks HIGH whenever structured
    reference context could be present. Provider credentials and Provider calls
    remain server-side.
    """

    def __init__(self, app: Any):
        self.app = app

    @property
    def state(self) -> Any:
        return self.app.state

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if (
            scope.get("type") != "http"
            or str(scope.get("method", "GET")).upper() != "POST"
            or scope.get("path") not in _CHAT_PATHS
        ):
            await self.app(scope, receive, send)
            return

        body_parts: list[bytes] = []
        while True:
            event = await receive()
            if event.get("type") != "http.request":
                if event.get("type") == "http.disconnect":
                    return
                continue
            chunk = event.get("body", b"")
            if chunk:
                body_parts.append(bytes(chunk))
                if sum(len(part) for part in body_parts) > MAX_GUARD_BODY_BYTES:
                    response = _error("request_too_large", "요청이 너무 큽니다.", status_code=413)
                    await response(scope, receive, send)
                    return
            if not event.get("more_body", False):
                break
        body = b"".join(body_parts)

        replayed = False

        async def replay_receive() -> dict[str, Any]:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        headers = _headers(scope)
        try:
            profile = validate_public_profile_selection(
                headers.get("x-padiem-model-profile"),
                headers.get("x-padiem-high-contributor-ack"),
            )
        except ModelPolicyError as exc:
            response = _error(exc.code, exc.message)
            await response(scope, replay_receive, send)
            return

        raw: Any = None
        try:
            raw = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass

        if profile == "high" and isinstance(raw, dict):
            has_attachment = bool(raw.get("attachments"))
            has_tool = raw.get("tool") is not None or "tool_input" in raw
            has_project = raw.get("project_id") is not None
            if has_attachment or has_tool or has_project:
                response = _error(
                    "high_reference_context_blocked",
                    "HIGH는 파일·프로젝트·웹 도구 같은 참고 자료와 함께 사용할 수 없습니다. 참고 자료를 제거하거나 기본 AI 품질을 사용해 주세요.",
                )
                await response(scope, replay_receive, send)
                return
            try:
                stored_project = await _stored_conversation_uses_project(self.app, scope, raw)
            except RuntimeError:
                response = _error(
                    "high_context_check_unavailable",
                    "HIGH를 안전하게 확인할 수 없어 요청을 중단했습니다. 기본 AI 품질을 사용해 주세요.",
                    status_code=503,
                )
                await response(scope, replay_receive, send)
                return
            if stored_project:
                response = _error(
                    "high_reference_context_blocked",
                    "HIGH는 프로젝트에 연결된 대화에서 사용할 수 없습니다. 프로젝트를 나가거나 기본 AI 품질을 사용해 주세요.",
                )
                await response(scope, replay_receive, send)
                return

        token = set_request_profile(profile)
        try:
            await self.app(scope, replay_receive, send)
        finally:
            reset_request_profile(token)


def guard_app(app: Any) -> ProfileGuard:
    return app if isinstance(app, ProfileGuard) else ProfileGuard(app)
