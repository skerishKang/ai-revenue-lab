"""#4647: Start an owner-scoped, provider-direct Drive upload without audio bytes.

The only accepted upload authority is a server-injected port that MUST attest
canonical Google OAuth Drive WRITE scope and start a resumable session through
the already trusted connector. No bearer token, Google refresh token, source
audio, or browser-selected workspace enters this route. Missing port => 503.
"""
from __future__ import annotations

import inspect
import json
import re
import secrets
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit, parse_qs

from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id
from .same_origin_guard import expected_browser_origin
from .bounded_request_body import read_bounded_request_body, RequestBodyTooLarge

MEETING_DRIVE_SESSION_PATH = "/api/claw/meeting/drive-upload-session"
_MAX_JSON_BYTES = 1200
_MEDIA_TYPES = {"audio/webm": (180 * 1024 * 1024, "webm"),
                "audio/mp4": (180 * 1024 * 1024, "m4a"),
                "audio/ogg": (180 * 1024 * 1024, "ogg"),
                "text/plain": (10 * 1024 * 1024, "txt")}
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
_NO_STORE = {"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache",
             "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff"}


def _error(status: int, code: str) -> JSONResponse:
    return JSONResponse({"ok": False, "error": {"code": code}},
                        status_code=status, headers=_NO_STORE)


async def _await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _session_uri_valid(uri: Any) -> bool:
    if not isinstance(uri, str) or len(uri) > 4096:
        return False
    try:
        parts = urlsplit(uri)
        query = parse_qs(parts.query, keep_blank_values=True)
    except (ValueError, TypeError):
        return False
    return (parts.scheme == "https" and parts.hostname == "www.googleapis.com"
            and parts.port is None and parts.username is None and parts.password is None
            and parts.path == "/upload/drive/v3/files"
            and query.get("uploadType") == ["resumable"]
            and len(query.get("upload_id", [])) == 1
            and bool(query["upload_id"][0])
            and not parts.fragment)


async def meeting_drive_upload_session(request: Request) -> JSONResponse:
    """Mint a resumable session URI for *this* signed-in owner, not a Drive grant."""
    if request.query_params:
        return _error(400, "meeting_upload_query_forbidden")
    expected = expected_browser_origin(request.app.state.settings)
    if not expected or request.headers.get("origin") != expected:
        return _error(403, "meeting_upload_origin_rejected")
    if not auth_ready(request):
        return _error(401, "authentication_required")
    owner = current_user_id(request)
    if not isinstance(owner, str) or not owner:
        return _error(401, "authentication_required")
    if request.headers.get("content-type", "").split(";", 1)[0].lower().strip() != "application/json":
        return _error(415, "meeting_upload_json_required")
    try:
        raw = await read_bounded_request_body(request, max_bytes=_MAX_JSON_BYTES)
        body = json.loads(raw)
    except (RequestBodyTooLarge, UnicodeError, ValueError, json.JSONDecodeError):
        return _error(400, "meeting_upload_invalid_request")
    if not isinstance(body, dict) or set(body) != {"mime_type", "byte_size"}:
        return _error(400, "meeting_upload_invalid_request")
    mime = body["mime_type"]
    size = body["byte_size"]
    if mime not in _MEDIA_TYPES or type(size) is not int or not 1 <= size <= _MEDIA_TYPES[mime][0]:
        return _error(400, "meeting_upload_invalid_media")
    history = getattr(request.app.state, "history_store", None)
    shadow_store = getattr(request.app.state, "identity_shadow_store", None)
    identity = getattr(request.app.state, "control_plane_identity_authority", None)
    uploader = getattr(request.app.state, "meeting_drive_upload_session_port", None)
    if not all((history, shadow_store, identity, uploader)):
        return _error(503, "meeting_drive_write_unavailable")
    try:
        profile = await _await(history.get_user(owner))
        if profile is None:
            return _error(401, "authentication_required")
        shadow = await _await(shadow_store.load_projection(owner))
        session_id = getattr(shadow, "auth_session_id", None)
        if not isinstance(session_id, str) or not session_id:
            return _error(503, "meeting_identity_unavailable")
        workspace = await _await(identity.resolve_connector_workspace(session_id=session_id))
        if not isinstance(workspace, str) or not workspace:
            return _error(503, "meeting_workspace_unavailable")
        # Filename is minted by the trusted service. Browser cannot specify
        # a file path, folder, Drive account, session ref or OAuth scope.
        filename = ("padiem-meeting-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                    + "-" + secrets.token_hex(8) + "." + _MEDIA_TYPES[mime][1])
        start = getattr(uploader, "begin_authorized_upload", None)
        if not callable(start):
            return _error(503, "meeting_drive_write_unavailable")
        result = await _await(start(owner_id=owner, workspace_ref=workspace,
                                    filename=filename, mime_type=mime, byte_size=size))
        uri = result.get("session_uri") if isinstance(result, dict) else None
        if not _session_uri_valid(uri):
            return _error(503, "meeting_drive_session_invalid")
        return JSONResponse({"ok": True, "session_uri": uri, "filename": filename,
                             "byte_size": size, "mime_type": mime},
                            headers=_NO_STORE)
    except Exception:
        # Never leak Drive provider errors or grant/credential material.
        return _error(503, "meeting_drive_write_unavailable")
