"""#3929/#3932: owner-scoped Drive artifact bytes, only via an authorized host READ.

Drive browser login and historic WRITE receipts are not READ grants.
No provider transport, OAuth token or new grant is created by this module.
"""
from __future__ import annotations

import hashlib
import inspect
import re
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .auth_routes import auth_ready, current_user_id
from .claw_conversation_artifact_routes import _bounded_rows
from .claw_routes import _resolve_canonical_tenant
from .history import validate_conversation_id

_ARTIFACT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{5,127}$")
_PDF = "application/pdf"
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_MAX_BYTES = 10 * 1024 * 1024
_HEADERS = {
    "Cache-Control": "private, no-store, max-age=0",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Vary": "Cookie",
}


def _error(status: int, code: str) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": {"code": code}},
        status_code=status, headers=_HEADERS,
    )


async def _deliver(request: Request, *, preview: bool) -> Response:
    owner = current_user_id(request) if auth_ready(request) else None
    if not owner:
        return _error(401, "unauthorized")
    try:
        conversation = validate_conversation_id(request.path_params.get("conversation_id"))
    except (TypeError, ValueError):
        return _error(400, "invalid_conversation_id")
    if conversation is None:
        return _error(400, "invalid_conversation_id")
    artifact_id = request.path_params.get("artifact_id")
    if not isinstance(artifact_id, str) or not _ARTIFACT_ID.fullmatch(artifact_id):
        return _error(400, "invalid_artifact_id")

    workspace = await _resolve_canonical_tenant(request)
    if not isinstance(workspace, str) or not workspace:
        return _error(403, "workspace_scope_unavailable")

    store = getattr(request.app.state, "history_store", None)
    verify = getattr(store, "verify_owner_conversation_artifacts", None)
    find = getattr(store, "get_owner_conversation_artifact", None)
    if not callable(verify) or not callable(find):
        return _error(503, "artifact_index_unavailable")
    try:
        owned = verify(owner, conversation)
        if inspect.isawaitable(owned):
            owned = await owned
        if owned is not True:
            return _error(404, "artifact_not_found")
        row = find(user_id=owner, conversation_id=conversation,
                   workspace_ref=workspace, artifact_id=artifact_id)
        if inspect.isawaitable(row):
            row = await row
        if row is None:
            return _error(404, "artifact_not_found")
        record = _bounded_rows([row])[0].record
        if (record.artifact_id != artifact_id
                or record.workspace_ref != workspace
                or record.media_type not in (_PDF, _XLSX)
                or record.size_bytes > _MAX_BYTES
                or record.durable_location is None
                or record.durable_location.location_kind != "google_drive"):
            return _error(503, "artifact_index_invalid")
    except Exception:
        return _error(503, "artifact_index_read_failed")

    if preview and record.media_type != _PDF:
        return JSONResponse({"ok": True, "preview": {
            "available": False, "kind": "download_only",
            "reason": "xlsx_preview_not_supported", "download_available": True,
        }}, headers=_HEADERS)

    # Only an explicitly composed trusted host may revalidate current READ
    # authority. The upload adapter cannot satisfy this contract.
    reader = getattr(request.app.state, "claw_drive_artifact_reader", None)
    fetch = getattr(reader, "read_authorized_artifact", None)
    if not callable(fetch):
        return _error(503, "drive_read_not_configured")
    try:
        data = fetch(owner_id=owner, workspace_ref=workspace, artifact=record)
        if inspect.isawaitable(data):
            data = await data
    except Exception:
        return _error(503, "drive_read_unavailable")
    if (type(data) is not bytes or not data
            or len(data) != record.size_bytes or len(data) > _MAX_BYTES
            or hashlib.sha256(data).hexdigest() != record.integrity_ref):
        return _error(503, "artifact_integrity_failed")
    if record.media_type == _PDF and (
        not data.startswith(b"%PDF-") or b"%%EOF" not in data[-1024:]
    ):
        return _error(503, "artifact_integrity_failed")
    if record.media_type == _XLSX and not data.startswith(b"PK\\x03\\x04"):
        return _error(503, "artifact_integrity_failed")

    disposition = "inline" if preview else "attachment"
    return Response(
        data, status_code=200, media_type=record.media_type,
        headers={
            **_HEADERS,
            "Content-Disposition": (
                f"{disposition}; filename*=UTF-8''"
                + quote(record.filename, safe="")
            ),
            "Content-Length": str(len(data)),
            **({"X-Frame-Options": "SAMEORIGIN"} if preview else {}),
        },
    )


async def claw_drive_artifact_download(request: Request) -> Response:
    return await _deliver(request, preview=False)


async def claw_drive_artifact_preview(request: Request) -> Response:
    return await _deliver(request, preview=True)


PRODUCTION_DRIVE_ARTIFACT_READER_COMPOSED = False
