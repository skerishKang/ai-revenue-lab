from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import current_user_id
from .config import Settings
from .control_plane_identity import IdentityBridgeError
from .control_plane_identity_worker import PrivateGoogleConnectTicket


MAX_TICKET_REQUEST_BODY_BYTES = 1_024
_REVIEWED_CONNECTORS = frozenset({"gmail", "google-drive"})
_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


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


async def _closed_body(request: Request) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise IdentityBridgeError(415, "connector_ticket_json_required", "JSON 요청만 허용됩니다.")
    raw = await request.body()
    if not raw or len(raw) > MAX_TICKET_REQUEST_BODY_BYTES:
        raise IdentityBridgeError(400, "connector_ticket_body_invalid", "연결 요청 형식이 올바르지 않습니다.")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IdentityBridgeError(400, "connector_ticket_body_invalid", "연결 요청 형식이 올바르지 않습니다.") from exc
    if not isinstance(payload, dict) or set(payload) != {"connector_id"}:
        raise IdentityBridgeError(400, "connector_ticket_body_invalid", "연결 요청 형식이 올바르지 않습니다.")
    connector_id = payload.get("connector_id")
    if connector_id not in _REVIEWED_CONNECTORS:
        raise IdentityBridgeError(403, "connector_not_reviewed", "허용되지 않은 연결입니다.")
    return {"connector_id": connector_id}


async def google_connector_ticket(request: Request) -> JSONResponse:
    """Return one short-lived credential to an authenticated same-origin B62 user.

    Browser input selects only the reviewed connector. Canonical session,
    actor/account/workspace references, scopes, ticket id and signature all remain
    server-owned Control Plane authority.
    """

    settings: Settings = request.app.state.settings
    expected_origin = _expected_origin(settings)
    request_origin = request.headers.get("origin")
    if expected_origin is None:
        return _error(503, "connector_ticket_unavailable", "Google 연결을 현재 사용할 수 없습니다.")
    if request_origin != expected_origin:
        return _error(403, "connector_ticket_origin_rejected", "Google 연결 요청의 출처를 확인할 수 없습니다.")

    user_id = current_user_id(request)
    if user_id is None:
        return _error(401, "authentication_required", "로그인이 필요합니다.")

    history_store = getattr(request.app.state, "history_store", None)
    authority = getattr(request.app.state, "control_plane_identity_authority", None)
    shadow_store = getattr(request.app.state, "identity_shadow_store", None)
    if history_store is None or authority is None or shadow_store is None:
        return _error(503, "connector_ticket_unavailable", "Google 연결을 현재 사용할 수 없습니다.")

    try:
        profile = await history_store.get_user(user_id)
    except Exception:
        return _error(503, "connector_ticket_unavailable", "Google 연결을 현재 사용할 수 없습니다.")
    if profile is None:
        return _error(401, "authentication_required", "로그인이 필요합니다.")

    try:
        payload = await _closed_body(request)
        shadow = await shadow_store.load_projection(user_id)
        if shadow is None:
            raise IdentityBridgeError(
                503,
                "control_plane_identity_not_linked",
                "Canonical identity is not linked for this product session.",
            )
        receipt = await authority.issue_google_connect_ticket(
            session_id=shadow.auth_session_id,
            connector_id=payload["connector_id"],
        )
    except IdentityBridgeError as exc:
        return _error(exc.status_code, exc.code, "Google 연결 요청을 승인할 수 없습니다.")
    except Exception:
        return _error(503, "connector_ticket_unavailable", "Google 연결을 현재 사용할 수 없습니다.")

    if not isinstance(receipt, PrivateGoogleConnectTicket):
        return _error(503, "connector_ticket_invalid", "Google 연결을 현재 사용할 수 없습니다.")

    return JSONResponse(
        {
            "ticket": {
                "connect_ticket": receipt.connect_ticket,
                "connector_id": receipt.connector_id,
                "expires_at": receipt.expires_at.isoformat(),
            }
        },
        status_code=200,
        headers=_NO_STORE_HEADERS,
    )


GOOGLE_CONNECTOR_TICKET_ROUTE = True
AUTHENTICATED_SAME_ORIGIN_ONLY = True
CLIENT_CAN_SELECT_CONNECTOR_ONLY = True
CLIENT_ACCOUNT_WORKSPACE_AUTHORITY = False
RAW_TICKET_QUERY_PARAMETER = False
RAW_TICKET_LOGGED = False
