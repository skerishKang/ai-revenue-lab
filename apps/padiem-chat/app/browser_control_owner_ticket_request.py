"""#3782: signed-in B54 -> existing private Engine P01 pending-ticket request.

SOURCE ONLY: no route registration, new auth system, approval grant, or live
browser execution. The only browser-controlled field is continuation_ref;
product user, auth session and Engine caller are SERVER owned.
"""
from __future__ import annotations

import json
import re

from kagent.p01_adapter import P01_APP_ID
from padiem_ai_engine_client import PadiemAiEngineClient, PadiemAiEngineClientError
from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id
from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .control_plane_identity_shadow import resolve_refreshed_session

BROWSER_CONTROL_OWNER_TICKET_REQUEST_PATH = "/api/claw/browser-control/owner-ticket/request"
BROWSER_CONTROL_OWNER_TICKET_REQUEST_ROUTE_WIRED = False
MAX_BODY_BYTES = 512
_CONTINUATION = re.compile(r"^cont_[A-Za-z0-9_-]{8,123}$")
_NO_STORE = {"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"}


def _error(status: int, code: str) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": {"code": code}},
        status_code=status, headers=_NO_STORE,
    )


async def browser_control_owner_ticket_request(request: Request) -> JSONResponse:
    """Submit one original Engine continuation; NEVER submit owner/P01 claims."""
    if request.method != "POST":
        return _error(405, "method_not_allowed")
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        return _error(415, "unsupported_media_type")
    uid = current_user_id(request) if auth_ready(request) else None
    if uid is None:
        return _error(401, "unauthorized")
    try:
        raw = await read_bounded_request_body(request, max_bytes=MAX_BODY_BYTES)
        wire = json.loads(raw.decode("utf-8"))
    except RequestBodyTooLarge:
        return _error(413, "request_too_large")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error(400, "invalid_json")
    if (
        type(wire) is not dict
        or set(wire) != {"continuation_ref"}
        or type(wire["continuation_ref"]) is not str
        or _CONTINUATION.fullmatch(wire["continuation_ref"]) is None
    ):
        return _error(422, "invalid_browser_ticket_request")

    state = request.app.state
    client = getattr(state, "browser_control_owner_ticket_engine_client", None)
    shadow = getattr(state, "identity_shadow_store", None)
    authority = getattr(state, "control_plane_identity_authority", None)
    if (
        type(client) is not PadiemAiEngineClient
        or client.app_id != P01_APP_ID
        or shadow is None or authority is None
    ):
        return _error(503, "browser_ticket_authority_unavailable")
    try:
        current = await resolve_refreshed_session(
            authority=authority, store=shadow, product_user_id=uid,
        )
        ref = await client.issue_browser_control_owner_ticket(
            continuation_ref=wire["continuation_ref"],
            product_user_id=uid, auth_session_ref=current.session_id,
        )
    except PadiemAiEngineClientError:
        # The Engine owns original pause and separate owner D1. Never reveal
        # whether a foreign continuation or approval record exists.
        return _error(503, "browser_ticket_authority_unavailable")
    except Exception:  # noqa: BLE001 - CP/Engine outages always fail closed
        return _error(503, "browser_ticket_authority_unavailable")
    return JSONResponse(
        {
            "ok": True, "ticket_ref": ref,
            "owner_approval_recorded": False,
            "browser_action_executed": False,
        },
        headers=_NO_STORE,
    )
