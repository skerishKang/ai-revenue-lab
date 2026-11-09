"""Owner-authenticated Google Drive disconnect. Only the canonical OAuth store may revoke."""
from __future__ import annotations

import inspect
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import current_user_id
from .calendar_session_authority import (
    CALENDAR_PATH_DISCONNECT,
    CALENDAR_SESSION_NO_TRUSTED_AUTHORITY,
    CALENDAR_SESSION_UNAVAILABLE,
    resolve_calendar_session,
)
from .same_origin_guard import expected_browser_origin


_HEADERS = {"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"}


def _reply(status: int, code: str) -> JSONResponse:
    return JSONResponse({"ok": False, "error": {"code": code}}, status_code=status, headers=_HEADERS)


async def _value(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


async def disconnect_google_drive(request: Request) -> JSONResponse:
    """No client-selected workspace/credential/binding and no provider token exposure.

    This revokes PADIEM's stored Drive credential, NOT the user's Google account.
    The canonical workspace is resolved from a real PADIEM product session.
    """
    return await _disconnect(
        request,
        binding_method="disconnect_drive",
        unavailable_code="connector_disconnect_unavailable",
    )


async def disconnect_google_calendar(request: Request) -> JSONResponse:
    """#7248: same Drive disconnect path, for the reviewed Calendar connector.

    The whole Calendar binding family of the trusted workspace is retired, which
    is also the only recovery from duplicates accumulated by older reconnects.
    Client input stays empty: workspace, binding and scopes are all server-derived.
    """
    return await _disconnect(
        request,
        binding_method="disconnect_calendar",
        unavailable_code="calendar_disconnect_unavailable",
    )


async def _disconnect(
    request: Request,
    *,
    binding_method: str,
    unavailable_code: str,
) -> JSONResponse:
    """Shared owner-authenticated disconnect path (Drive + Calendar)."""
    if request.query_params:
        return _reply(400, "connector_disconnect_query_not_allowed")
    expected = expected_browser_origin(request.app.state.settings)
    if not expected or request.headers.get("origin") != expected:
        return _reply(403, "connector_disconnect_origin_rejected")
    # No browser-supplied workspace / binding / connector / scope is accepted.
    # The endpoint takes an empty body and the origin-verified cookie only.
    if request.headers.get("content-length") not in (None, "", "0"):
        return _reply(400, "connector_disconnect_body_not_allowed")
    if request.headers.get("transfer-encoding"):
        return _reply(400, "connector_disconnect_body_not_allowed")
    # #7261: the workspace this revoke names is derived from the one session
    # every calendar path resolves through, never from the shadow pointer read
    # on its own (two readings is how a screen and a turn disagreed before).
    calendar_session = await resolve_calendar_session(
        request, path=CALENDAR_PATH_DISCONNECT
    )
    if not calendar_session.resolved:
        if calendar_session.reason == CALENDAR_SESSION_NO_TRUSTED_AUTHORITY:
            return _reply(401, "authentication_required")
        if calendar_session.reason == CALENDAR_SESSION_UNAVAILABLE:
            return _reply(503, unavailable_code)
        return _reply(503, "canonical_session_unavailable")
    uid = current_user_id(request)
    identity = getattr(request.app.state, "control_plane_identity_authority", None)
    google = getattr(request.app.state, "google_oauth_workspace_truth", None)
    if identity is None or google is None:
        return _reply(503, unavailable_code)
    try:
        session_id = calendar_session.session_id
        workspace = await _value(identity.resolve_connector_workspace(session_id=session_id))
        if not isinstance(workspace, str) or not workspace:
            return _reply(503, "canonical_workspace_unavailable")
        result = await _value(
            getattr(google, binding_method)(workspace_ref=workspace)
        )
        # Drive answers a bool, Calendar a bounded revocation count.
        if not isinstance(result, bool) and (
            not isinstance(result, int) or not 0 <= result <= 32
        ):
            return _reply(503, "connector_disconnect_unverified")
    except Exception:
        return _reply(503, unavailable_code)
    # The connector tool offer is cached per user for one short window; a
    # revoked grant must stop being declared at once.
    from .chat_connector_tools import invalidate_connector_tool_grant_cache

    invalidate_connector_tool_grant_cache(uid)
    return JSONResponse(
        {"ok": True, "state": "off", "revoked": result},
        status_code=200, headers=_HEADERS,
    )
