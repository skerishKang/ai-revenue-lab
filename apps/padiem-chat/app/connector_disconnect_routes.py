"""Owner-authenticated Google Drive disconnect. Only the canonical OAuth store may revoke."""
from __future__ import annotations

import inspect
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id
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
    uid = current_user_id(request) if auth_ready(request) else None
    if not uid:
        return _reply(401, "authentication_required")
    history = getattr(request.app.state, "history_store", None)
    shadow_store = getattr(request.app.state, "identity_shadow_store", None)
    identity = getattr(request.app.state, "control_plane_identity_authority", None)
    google = getattr(request.app.state, "google_oauth_workspace_truth", None)
    if not all((history, shadow_store, identity, google)):
        return _reply(503, "connector_disconnect_unavailable")
    try:
        profile = await _value(history.get_user(uid))
        if profile is None:
            return _reply(401, "authentication_required")
        shadow = await _value(shadow_store.load_projection(uid))
        session_id = getattr(shadow, "auth_session_id", None)
        if not isinstance(session_id, str) or not session_id:
            return _reply(503, "canonical_session_unavailable")
        workspace = await _value(identity.resolve_connector_workspace(session_id=session_id))
        if not isinstance(workspace, str) or not workspace:
            return _reply(503, "canonical_workspace_unavailable")
        result = await _value(google.disconnect_drive(workspace_ref=workspace))
        if result not in (True, False):
            return _reply(503, "connector_disconnect_unverified")
    except Exception:
        return _reply(503, "connector_disconnect_unavailable")
    return JSONResponse(
        {"ok": True, "state": "off", "revoked": result},
        status_code=200, headers=_HEADERS,
    )
