from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any
from urllib.parse import urlsplit

from . import httpx_compat as httpx

from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import current_user_id
from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .config import Settings
from .control_plane_identity import IdentityBridgeError
from .control_plane_identity_worker import PrivateGoogleConnectTicket
from .same_origin_guard import expected_browser_origin, expected_browser_origins


MAX_TICKET_REQUEST_BODY_BYTES = 1_024
MAX_CONNECT_START_RESPONSE_BYTES = 64 * 1024
GOOGLE_OAUTH_CONNECT_URL = "https://oauth.padiem.net/v1/google/connect"
# #7553: the browser that starts a Google connection receives a random value in
# this cookie (Domain = the OAuth host's parent, Path = the OAuth callback) and
# only its SHA-256 goes to the private runtime. The OAuth edge returns the
# cookie with the callback, so the connection completes only in this browser.
GOOGLE_OAUTH_BROWSER_BINDING_COOKIE = "padiem_google_oauth_bind"
GOOGLE_OAUTH_CALLBACK_PATH = "/v1/google/callback"
GOOGLE_OAUTH_BROWSER_BINDING_MAX_AGE = 600


def _browser_binding_cookie_domain() -> str | None:
    labels = (urlsplit(GOOGLE_OAUTH_CONNECT_URL).hostname or "").lower().split(".")
    if len(labels) < 3 or not all(labels):
        return None
    return ".".join(labels[1:])

_REVIEWED_CONNECTORS = frozenset({"gmail", "google-drive", "google-calendar"})
# #3289: the reviewed connectors whose OAuth handoff the product surface may
# start. Each maps to exactly one control-plane reviewed readonly scope set;
# Drive is https://www.googleapis.com/auth/drive.readonly and never widens it.
# Gmail (#7088) joins with the already-registered gmail.readonly scope set.
_OAUTH_START_REVIEWED_CONNECTORS = frozenset({"gmail", "google-calendar", "google-drive"})
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


async def _closed_body(request: Request) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise IdentityBridgeError(415, "connector_ticket_json_required", "JSON 요청만 허용됩니다.")
    try:
        raw = await read_bounded_request_body(
            request,
            max_bytes=MAX_TICKET_REQUEST_BODY_BYTES,
        )
    except RequestBodyTooLarge as exc:
        raise IdentityBridgeError(
            400,
            "connector_ticket_body_invalid",
            "연결 요청 형식이 올바르지 않습니다.",
        ) from exc
    if not raw:
        raise IdentityBridgeError(400, "connector_ticket_body_invalid", "연결 요청 형식이 올바르지 않습니다.")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IdentityBridgeError(400, "connector_ticket_body_invalid", "연결 요청 형식이 올바르지 않습니다.") from exc
    if not isinstance(payload, dict) or set(payload) not in ({"connector_id"}, {"connector_id", "begin_oauth"}):
        raise IdentityBridgeError(400, "connector_ticket_body_invalid", "연결 요청 형식이 올바르지 않습니다.")
    connector_id = payload.get("connector_id")
    if connector_id not in _REVIEWED_CONNECTORS:
        raise IdentityBridgeError(403, "connector_not_reviewed", "허용되지 않은 연결입니다.")
    begin_oauth = payload.get("begin_oauth", False)
    if not isinstance(begin_oauth, bool):
        raise IdentityBridgeError(400, "connector_ticket_body_invalid", "연결 요청 형식이 올바르지 않습니다.")
    if begin_oauth and connector_id not in _OAUTH_START_REVIEWED_CONNECTORS:
        raise IdentityBridgeError(403, "connector_oauth_start_not_reviewed", "허용되지 않은 연결입니다.")
    return {"connector_id": connector_id, "begin_oauth": begin_oauth}


async def google_connector_ticket(request: Request) -> JSONResponse:
    """Return one short-lived credential to an authenticated same-origin B62 user.

    Browser input selects only the reviewed connector. Canonical session,
    actor/account/workspace references, scopes, ticket id and signature all remain
    server-owned Control Plane authority.
    """

    settings: Settings = request.app.state.settings
    # The #3476 middleware already covers cookie-authenticated browser traffic,
    # but this route answers origin problems before it resolves a session, so it
    # keeps its own check. The expected-origin derivation is single-sourced.
    expected_origin = expected_browser_origin(settings)
    request_origin = request.headers.get("origin")
    if expected_origin is None:
        return _error(503, "connector_ticket_unavailable", "Google 연결을 현재 사용할 수 없습니다.")
    if request_origin != expected_origin:
        # #7607: the parallel pages.dev entry is a reviewed origin for ordinary
        # mutations (#6850), but the connect handoff cannot finish there — the
        # #7553 browser binding cookie is set for the parent domain by a
        # cross-site response and the OAuth callback returns to this host. That
        # is visible here, before any ticket or Google authorization exists, so
        # answer with where the connection can be started instead of a generic
        # origin rejection after a silent callback failure.
        reviewed = expected_browser_origins(settings)
        if request_origin in reviewed:
            canonical_host = urlsplit(expected_origin).netloc
            return _error(
                403,
                "connector_ticket_origin_not_canonical",
                f"Google 연결은 {canonical_host} 에서 시작해 주세요.",
            )
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

    if payload["begin_oauth"] is True:
        return await _begin_google_oauth(
            request,
            receipt=receipt,
            expected_origin=expected_origin,
        )

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


async def _bounded_upstream_json(response: Any) -> dict[str, Any]:
    raw = bytearray()
    async for chunk in response.aiter_bytes():
        if len(raw) + len(chunk) > MAX_CONNECT_START_RESPONSE_BYTES:
            raise ValueError("Google OAuth start response exceeds the trusted bound")
        raw.extend(chunk)
    if response.status_code != 200:
        raise ValueError("Google OAuth start was rejected")
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Google OAuth start response is invalid") from exc
    if not isinstance(document, dict) or set(document) != {"ok", "authorization"} or document.get("ok") is not True:
        raise ValueError("Google OAuth start response is not closed")
    authorization = document.get("authorization")
    if not isinstance(authorization, dict):
        raise ValueError("Google OAuth start authorization is invalid")
    required = {"authorization_url", "connector_id", "expires_at"}
    if not required.issubset(authorization):
        raise ValueError("Google OAuth start authorization is incomplete")
    if any(not isinstance(authorization.get(key), str) or not authorization.get(key) for key in required):
        raise ValueError("Google OAuth start authorization is invalid")
    return {
        "authorization_url": authorization["authorization_url"],
        "connector_id": authorization["connector_id"],
        "expires_at": authorization["expires_at"],
    }


async def _begin_google_oauth(
    request: Request,
    *,
    receipt: PrivateGoogleConnectTicket,
    expected_origin: str,
) -> JSONResponse:
    """Begin a reviewed Google connector OAuth handoff without returning the
    connect ticket to JavaScript. Caller-provided connector input is already
    closed to the reviewed set, so Drive can only ever request
    drive.readonly through the same server-owned exchange.
    """
    browser_binding = secrets.token_urlsafe(32)
    browser_binding_digest = hashlib.sha256(browser_binding.encode("utf-8")).hexdigest()
    try:
        oauth_client = getattr(request.app.state, "google_oauth", None)
        transport = getattr(oauth_client, "transport", None)
        timeout = httpx.Timeout(15.0, connect=8.0)
        async with httpx.AsyncClient(transport=transport, timeout=timeout, follow_redirects=False) as client:
            async with client.stream(
                "POST",
                GOOGLE_OAUTH_CONNECT_URL,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Origin": expected_origin,
                },
                json={
                    "connect_ticket": receipt.connect_ticket,
                    "browser_binding_digest": browser_binding_digest,
                },
            ) as response:
                authorization = await _bounded_upstream_json(response)
        if authorization["connector_id"] != receipt.connector_id:
            raise ValueError("Google OAuth connector mismatch")
    except (ValueError, TypeError, httpx.HTTPError):
        return _error(502, "connector_oauth_start_unavailable", "Google 연결을 시작할 수 없습니다.")

    response = JSONResponse(
        {"authorization": authorization},
        status_code=200,
        headers=_NO_STORE_HEADERS,
    )
    response.set_cookie(
        GOOGLE_OAUTH_BROWSER_BINDING_COOKIE,
        browser_binding,
        max_age=GOOGLE_OAUTH_BROWSER_BINDING_MAX_AGE,
        path=GOOGLE_OAUTH_CALLBACK_PATH,
        domain=_browser_binding_cookie_domain(),
        secure=True,
        httponly=True,
        samesite="lax",
    )
    return response


GOOGLE_CONNECTOR_TICKET_ROUTE = True
GOOGLE_CONNECTOR_INLINE_OAUTH_START = True
OAUTH_START_REVIEWED_CONNECTORS = tuple(sorted(_OAUTH_START_REVIEWED_CONNECTORS))
RAW_CONNECT_TICKET_IN_JAVASCRIPT = False
AUTHENTICATED_SAME_ORIGIN_ONLY = True
CLIENT_CAN_SELECT_CONNECTOR_ONLY = True
CLIENT_ACCOUNT_WORKSPACE_AUTHORITY = False
RAW_TICKET_QUERY_PARAMETER = False
RAW_TICKET_LOGGED = False
