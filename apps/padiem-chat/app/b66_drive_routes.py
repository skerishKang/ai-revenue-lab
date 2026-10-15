"""B66 #4089 owner-authenticated Drive.file host routes.

The browser supplies no owner, canonical workspace, actor, scope, credential,
binding reference or provider token. The signed PADIEM cookie selects one B66
owner and the server composes the existing Control Plane authorities only.
"""
from __future__ import annotations

import inspect
import json
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id
from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .b66_drive_file_host import B66DriveFileHost
from .same_origin_guard import expected_browser_origin


_HEADERS = {"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"}
_MAX_CALLBACK_BODY_BYTES = 8_192
_CALLBACK_KEYS = frozenset({"state_ref", "authorization_code", "provider_error"})


def _reply(status: int, code: str) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": {"code": code}},
        status_code=status,
        headers=_HEADERS,
    )


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _request_allows_no_input(request: Request) -> JSONResponse | None:
    if request.query_params:
        return _reply(400, "b66_drive_query_not_allowed")
    if request.headers.get("content-length") not in (None, "", "0"):
        return _reply(400, "b66_drive_body_not_allowed")
    if request.headers.get("transfer-encoding"):
        return _reply(400, "b66_drive_body_not_allowed")
    return None


async def _host(request: Request) -> tuple[str, B66DriveFileHost] | JSONResponse:
    expected_origin = expected_browser_origin(request.app.state.settings)
    if expected_origin is None:
        return _reply(503, "b66_drive_unavailable")
    if request.headers.get("origin") != expected_origin:
        return _reply(403, "b66_drive_origin_rejected")
    user_id = current_user_id(request) if auth_ready(request) else None
    if not user_id:
        return _reply(401, "authentication_required")
    history_store = getattr(request.app.state, "history_store", None)
    identity_shadow_store = getattr(request.app.state, "identity_shadow_store", None)
    identity_authority = getattr(request.app.state, "control_plane_identity_authority", None)
    google_oauth_authority = getattr(request.app.state, "google_oauth_workspace_truth", None)
    if not all(
        (
            history_store,
            identity_shadow_store,
            identity_authority,
            google_oauth_authority,
        )
    ):
        return _reply(503, "b66_drive_unavailable")
    try:
        profile = await _maybe_await(history_store.get_user(user_id))
    except Exception:
        return _reply(503, "b66_drive_unavailable")
    if profile is None:
        return _reply(401, "authentication_required")
    host = B66DriveFileHost(
        identity_shadow_store=identity_shadow_store,
        identity_authority=identity_authority,
        google_oauth_authority=google_oauth_authority,
    )
    return user_id, host


def _failure(exc: Exception) -> JSONResponse:
    if str(exc) == "signed_padiem_session_required":
        return _reply(401, "authentication_required")
    return _reply(503, "b66_drive_unavailable")


async def b66_drive_status(request: Request) -> JSONResponse:
    """Return one B66 owner's own Drive.file connection status."""

    body_error = _request_allows_no_input(request)
    if body_error is not None:
        return body_error
    composed = await _host(request)
    if isinstance(composed, JSONResponse):
        return composed
    _, host = composed
    try:
        status = await host.status(request=request)
    except Exception as exc:
        return _failure(exc)
    return JSONResponse(
        {"ok": True, "status": status},
        status_code=200,
        headers=_HEADERS,
    )


async def b66_drive_connect(request: Request) -> JSONResponse:
    """Start the server-issued B66 Drive.file OAuth handoff for one owner."""

    body_error = _request_allows_no_input(request)
    if body_error is not None:
        return body_error
    composed = await _host(request)
    if isinstance(composed, JSONResponse):
        return composed
    _, host = composed
    try:
        receipt = await host.start_connect(request=request)
    except Exception as exc:
        return _failure(exc)
    return JSONResponse(
        {"ok": True, "connect": receipt},
        status_code=200,
        headers=_HEADERS,
    )


async def b66_drive_connect_callback(request: Request) -> JSONResponse:
    """Complete one consumed B66 callback state without exposing raw tokens."""

    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        return _reply(400, "b66_drive_json_required")
    try:
        raw = await read_bounded_request_body(
            request,
            max_bytes=_MAX_CALLBACK_BODY_BYTES,
        )
    except RequestBodyTooLarge:
        return _reply(400, "b66_drive_body_invalid")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _reply(400, "b66_drive_body_invalid")
    if not isinstance(payload, dict) or set(payload) != _CALLBACK_KEYS:
        return _reply(400, "b66_drive_body_invalid")
    state_ref = payload.get("state_ref")
    authorization_code = payload.get("authorization_code")
    provider_error = payload.get("provider_error")
    if not isinstance(state_ref, str) or not state_ref or len(state_ref) > 256:
        return _reply(400, "b66_drive_body_invalid")
    if authorization_code is not None and (
        not isinstance(authorization_code, str)
        or not authorization_code
        or len(authorization_code) > 4_096
    ):
        return _reply(400, "b66_drive_body_invalid")
    if provider_error is not None and (
        not isinstance(provider_error, str) or not provider_error or len(provider_error) > 1_024
    ):
        return _reply(400, "b66_drive_body_invalid")

    composed = await _host(request)
    if isinstance(composed, JSONResponse):
        return composed
    _, host = composed
    try:
        status = await host.complete_callback(
            request=request,
            state_ref=state_ref,
            authorization_code=authorization_code,
            provider_error=provider_error,
        )
    except Exception as exc:
        return _failure(exc)
    return JSONResponse(
        {"ok": True, "status": status},
        status_code=200,
        headers=_HEADERS,
    )


async def b66_drive_disconnect(request: Request) -> JSONResponse:
    """Revoke only this B66 owner's canonical Drive.file grant."""

    body_error = _request_allows_no_input(request)
    if body_error is not None:
        return body_error
    composed = await _host(request)
    if isinstance(composed, JSONResponse):
        return composed
    _, host = composed
    try:
        result = await host.disconnect(request=request)
    except Exception as exc:
        return _failure(exc)
    return JSONResponse(
        {"ok": True, "disconnect": result},
        status_code=200,
        headers=_HEADERS,
    )


B66_DRIVE_FILE_ROUTES_SERVER_ONLY = True
B66_DRIVE_FILE_ROUTES_CLIENT_AUTHORITY = False
