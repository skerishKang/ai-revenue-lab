"""Authenticated same-origin Calendar READ activation route (#2952)."""

from __future__ import annotations

import json
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import current_user_id
from .b54_canonical_session import resolve_current_b54_canonical_session
from .calendar_read_activation_engine import CalendarReadActivationClientError
from .config import Settings


_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}
_MAX_BODY_BYTES = 256


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message}},
        status_code=status,
        headers=_NO_STORE_HEADERS,
    )


def _expected_origin(settings: Settings) -> str | None:
    value = settings.public_base_url
    if not isinstance(value, str) or not value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc:
        return None
    return f"https://{parsed.netloc}"


async def _require_empty_json(request: Request) -> None:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise ValueError("json required")
    raw = await request.body()
    if not raw or len(raw) > _MAX_BODY_BYTES:
        raise ValueError("invalid body")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid json") from exc
    if payload != {}:
        raise ValueError("client authority is forbidden")


async def activate_google_calendar_read(request: Request) -> JSONResponse:
    """Activate the fixed Calendar READ grant from the current canonical session."""

    settings: Settings = request.app.state.settings
    expected_origin = _expected_origin(settings)
    if expected_origin is None:
        return _error(503, "calendar_read_activation_unavailable", "캘린더 읽기 활성화를 사용할 수 없습니다.")
    if request.headers.get("origin") != expected_origin:
        return _error(403, "calendar_read_activation_origin_rejected", "요청 출처를 확인할 수 없습니다.")
    if current_user_id(request) is None:
        return _error(401, "authentication_required", "로그인이 필요합니다.")

    try:
        await _require_empty_json(request)
    except ValueError:
        return _error(400, "calendar_read_activation_body_invalid", "활성화 요청 형식이 올바르지 않습니다.")

    current = await resolve_current_b54_canonical_session(request)
    if current is None:
        return _error(
            403,
            "current_b54_session_unavailable",
            "현재 Padiem 세션을 확인할 수 없습니다.",
        )

    client = getattr(request.app.state, "calendar_read_activation_client", None)
    if client is None:
        return _error(
            503,
            "calendar_read_activation_unavailable",
            "캘린더 읽기 활성화를 사용할 수 없습니다.",
        )

    session = getattr(current, "auth_session", None)
    session_id = getattr(session, "session_id", None)
    if not isinstance(session_id, str) or not session_id:
        return _error(
            403,
            "current_b54_session_unavailable",
            "현재 Padiem 세션을 확인할 수 없습니다.",
        )

    try:
        document = await client.activate(session_id=session_id)
    except CalendarReadActivationClientError:
        return _error(
            503,
            "calendar_read_activation_unavailable",
            "캘린더 읽기 활성화를 완료하지 못했습니다.",
        )

    return JSONResponse(
        {
            "ok": document["ok"],
            "calendar_read_grant": document["calendar_read_grant"],
            "calendar_write_authorized": False,
        },
        status_code=200,
        headers=_NO_STORE_HEADERS,
    )


CALENDAR_READ_ACTIVATION_ROUTE = True
CLIENT_SESSION_AUTHORITY = False
CLIENT_WORKSPACE_AUTHORITY = False
CLIENT_BINDING_AUTHORITY = False
CLIENT_ACTOR_AUTHORITY = False
CLIENT_CAPABILITY_AUTHORITY = False
CALENDAR_WRITE_AUTHORIZED = False
