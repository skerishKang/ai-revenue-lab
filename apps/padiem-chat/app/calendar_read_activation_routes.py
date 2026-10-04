"""Authenticated same-origin Calendar READ activation route (#2952).

#3434 follow-up — the route surfaces the bounded diagnostic stage of an Engine
rejection instead of folding every failure into one unavailable code. The
Engine's rejection body is read only by the client, which projects it onto the
closed safe vocabulary in ``app.calendar_read_activation_engine``; this route
re-validates the projected code against its own closed set below and attaches
a fixed Korean message per code. The Engine's raw message, and every private
reference (binding/actor/workspace/session/token), never reach this response:

``RAW_ENGINE_MESSAGE_OUTPUT = 0``
``BINDING_REF_OUTPUT = 0`` / ``ACTOR_REF_OUTPUT = 0`` /
``WORKSPACE_REF_OUTPUT = 0`` / ``SESSION_ID_OUTPUT = 0`` /
``OAUTH_TOKEN_OUTPUT = 0``

HTTP statuses preserve the Engine's user-actionable semantics where they exist
(403 workspace unavailable, 409 not-connected/binding) and flatten to 503
where a preserved status would mislead the browser (the Chat->Engine
credential family, whose Engine 401/403 is a server-side service fault).
"""

from __future__ import annotations

import json
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import current_user_id
from .b54_canonical_session import resolve_current_b54_canonical_session
from .calendar_read_activation_engine import (
    GENERIC_CALENDAR_READ_ACTIVATION_CODE,
    CALENDAR_ACTIVATION_SAFE_DIAGNOSTIC_CODES,
    CalendarReadActivationClientError,
)
from .config import Settings


_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}
_MAX_BODY_BYTES = 256

# Closed, static, per-code user guidance. Keys are exactly the client's safe
# diagnostic codes; no Engine text ever enters these messages.
_ACTIVATION_FAILURE_MESSAGES: dict[str, str] = {
    "calendar_activation_engine_auth_failed": "캘린더 읽기 활성화 서비스 인증에 실패했습니다.",
    "calendar_activation_workspace_unavailable": "캘린더 활성화에 필요한 워크스페이스를 확인할 수 없습니다.",
    "calendar_activation_binding_unavailable": "캘린더 연결 정보를 확인할 수 없습니다.",
    "calendar_activation_not_connected": "Google Calendar가 아직 연결되어 있지 않습니다. 먼저 연결해 주세요.",
    "calendar_activation_grant_unavailable": "캘린더 읽기 권한 활성화를 완료하지 못했습니다.",
    GENERIC_CALENDAR_READ_ACTIVATION_CODE: "캘린더 읽기 활성화를 완료하지 못했습니다.",
}
# The only statuses the Engine's own emission table ever pairs with the mapped
# codes (403 workspace, 409 not-connected/binding, 503 everything server-side).
# Anything else folds back to 503 so the response surface stays closed.
_SAFE_FAILURE_STATUSES = frozenset({403, 409, 503})


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
    except CalendarReadActivationClientError as exc:
        # The client already projected the Engine rejection onto the closed
        # safe vocabulary; re-validate against this route's own closed set and
        # clamp the status so a misbehaving client still fails closed.
        code = getattr(exc, "diagnostic_code", None)
        if code not in _ACTIVATION_FAILURE_MESSAGES:
            code = GENERIC_CALENDAR_READ_ACTIVATION_CODE
        status = getattr(exc, "status_code", 503)
        if status not in _SAFE_FAILURE_STATUSES:
            status = 503
        return _error(status, code, _ACTIVATION_FAILURE_MESSAGES[code])

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
CALENDAR_WRITE_AUTHORITY_ADDED = 0
RAW_ENGINE_MESSAGE_OUTPUT = 0
BINDING_REF_OUTPUT = 0
ACTOR_REF_OUTPUT = 0
WORKSPACE_REF_OUTPUT = 0
SESSION_ID_OUTPUT = 0
OAUTH_TOKEN_OUTPUT = 0
SAFE_DIAGNOSTIC_CODES_CLOSED = frozenset(CALENDAR_ACTIVATION_SAFE_DIAGNOSTIC_CODES)
