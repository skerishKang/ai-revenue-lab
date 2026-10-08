"""#3782 signed B54 owner-only retry of independently recorded browser P01.

A first-party user may retry Engine verification after an owner D1 click was
persisted but the Engine service call failed. This cannot record approval,
forge decision fields, reissue a ticket, execute Input or dispatch a Broker
command. The original Engine/owner D1 are independently re-read on every call.
SOURCE ONLY: no registered Product route / Owner D1 binding in Production.
"""
from __future__ import annotations

import inspect
import json

from padiem_ai_engine_client import PadiemAiEngineClient, PadiemAiEngineClientError
from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id
from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .browser_control_owner_p01_decision import (
    NO_STORE,
    SAFE,
    ServerAdmittedBrowserControlOwnerTicket,
)
from .control_plane_identity_shadow import resolve_refreshed_session

BROWSER_CONTROL_OWNER_P01_FINALIZE_PATH = "/api/claw/browser-control/approvals/finalize"
BROWSER_CONTROL_OWNER_P01_FINALIZE_ROUTE_WIRED = False
MAX_BODY_BYTES = 512


def _error(status: int, code: str) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": {"code": code}, "browser_action_executed": False},
        headers=NO_STORE, status_code=status,
    )


async def browser_control_owner_p01_finalize(request: Request) -> JSONResponse:
    """Only owner ticket reference from authenticated B54 user; no approval data."""
    if request.method != "POST":
        return _error(405, "method_not_allowed")
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        return _error(415, "unsupported_media_type")
    uid = current_user_id(request) if auth_ready(request) else None
    if uid is None:
        return _error(401, "unauthorized")
    try:
        body = await read_bounded_request_body(request, max_bytes=MAX_BODY_BYTES)
        wire = json.loads(body.decode("utf-8"))
    except RequestBodyTooLarge:
        return _error(413, "request_too_large")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error(400, "invalid_json")
    if (
        type(wire) is not dict or set(wire) != {"ticket_ref"}
        or type(wire.get("ticket_ref")) is not str
        or SAFE.fullmatch(wire["ticket_ref"]) is None
    ):
        return _error(422, "invalid_browser_p01_finalize")

    state = request.app.state
    loader = getattr(state, "browser_control_owner_ticket_loader", None)
    owner_d1 = getattr(state, "browser_control_owner_p01_d1", None)
    engine_d1 = getattr(state, "browser_control_engine_d1", None)
    client = getattr(state, "browser_control_owner_resume_engine_client", None)
    shadow = getattr(state, "identity_shadow_store", None)
    authority = getattr(state, "control_plane_identity_authority", None)
    if (
        not callable(loader) or owner_d1 is None or engine_d1 is None
        or owner_d1 is engine_d1
        or type(client) is not PadiemAiEngineClient
        or shadow is None or authority is None
    ):
        return _error(503, "browser_p01_finalize_unavailable")
    try:
        session = await resolve_refreshed_session(
            authority=authority, store=shadow, product_user_id=uid,
        )
        workspace = session.tenant_id
        subject = session.subject.subject_id
        if (
            type(workspace) is not str or SAFE.fullmatch(workspace) is None
            or type(subject) is not str or SAFE.fullmatch(subject) is None
        ):
            return _error(503, "browser_p01_finalize_unavailable")
        ticket = loader(
            user_id=uid, workspace_ref=workspace, ticket_ref=wire["ticket_ref"],
        )
        if inspect.isawaitable(ticket):
            ticket = await ticket
        if (
            type(ticket) is not ServerAdmittedBrowserControlOwnerTicket
            or ticket.ticket_ref != wire["ticket_ref"]
            or ticket.session_user_id != uid
            or ticket.workspace_ref != workspace
            or ticket.engine_owner_subject_id != subject
            or ticket.app_id != client.app_id
        ):
            return _error(404, "browser_p01_ticket_unavailable")
        # Only Engine can decide whether a human actually approved. No
        # submitted decision or owner D1 write is performed in this route.
        completed = await client.resume_browser_control_owner_approval(
            continuation_ref=ticket.continuation_ref,
        )
        if completed is not True:
            return _error(503, "browser_p01_finalize_unavailable")
    except PadiemAiEngineClientError:
        return _error(503, "browser_p01_finalize_unavailable")
    except Exception:  # noqa: BLE001 - CP/Owner/Engine errors never grant control
        return _error(503, "browser_p01_finalize_unavailable")
    return JSONResponse(
        {
            "ok": True, "engine_approval_completed": True,
            "browser_action_executed": False,
            "broker_command_dispatched": False,
        },
        headers=NO_STORE,
    )
