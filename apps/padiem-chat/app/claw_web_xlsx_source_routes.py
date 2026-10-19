"""#3580 WEB-FIRST: owner-selected original XLSX bytes in private D1/R2.

This is web source intake, not an Engine P01 approval, editing tool, Excel/PDF
converter or Drive WRITE. The original file remains unchanged; the explicit
P01 processing approval will be composed in a separate web milestone.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .auth_routes import auth_ready, current_user_id
from .bounded_request_body import read_bounded_request_body, RequestBodyTooLarge
from .claw_memory_routes import _resolve_memory_workspace
from .workspace_storage import (
    MAX_WEB_XLSX_BYTES, WorkspaceStorageError, XLSX_MEDIA_TYPE,
)

WEB_SOURCES_PATH = "/api/claw/office/web-sources"
WEB_SOURCE_DOWNLOAD_PATH = "/api/claw/office/web-sources/{document_id}/download"
_ID = re.compile(r"^doc_[0-9a-f]{32}$")
_NO_STORE = {
    "Cache-Control": "private, no-store, max-age=0",
    "Pragma": "no-cache", "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}
_MAX_BODY = ((MAX_WEB_XLSX_BYTES + 2) // 3) * 4 + 512


def _error(status: int, code: str) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": {"code": code}},
        status_code=status, headers=_NO_STORE,
    )


async def _authority(request: Request):
    owner = current_user_id(request) if auth_ready(request) else None
    if not owner:
        return _error(401, "unauthorized")
    workspace = await _resolve_memory_workspace(request, owner)
    if not workspace:
        return _error(503, "workspace_authority_unavailable")
    store = getattr(request.app.state, "workspace_document_store", None)
    if store is None:
        return _error(503, "web_xlsx_store_unavailable")
    return store, owner, workspace


async def web_xlsx_sources(request: Request) -> Response:
    authority = await _authority(request)
    if isinstance(authority, Response):
        return authority
    store, owner, workspace = authority
    if request.method == "GET":
        try:
            files = await store.list_web_xlsx(
                tenant_id=workspace, owner_id=owner, workspace_id=workspace,
            )
        except (WorkspaceStorageError, ValueError, TypeError, AttributeError):
            return _error(503, "web_xlsx_list_unavailable")
        return JSONResponse({
            "ok": True, "contract_version": "claw-web-xlsx-source.v1",
            "files": files, "source": "browser_upload",
            "read_authorized_for_processing": False,
            "requires_p01_for_processing": True,
        }, headers=_NO_STORE)

    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        return _error(415, "unsupported_media_type")
    try:
        raw = await read_bounded_request_body(request, max_bytes=_MAX_BODY)
    except RequestBodyTooLarge:
        return _error(413, "web_xlsx_too_large")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return _error(400, "invalid_json")
    if not isinstance(data, dict) or set(data) != {"name", "base64"}:
        return _error(400, "invalid_web_xlsx_shape")
    encoded = data["base64"]
    if type(encoded) is not str or not encoded or len(encoded) > _MAX_BODY:
        return _error(422, "invalid_web_xlsx_payload")
    try:
        payload = base64.b64decode(encoded, validate=True)
        if not 0 < len(payload) <= MAX_WEB_XLSX_BYTES:
            return _error(413, "web_xlsx_too_large")
        file = await store.put_web_xlsx(
            tenant_id=workspace, owner_id=owner, workspace_id=workspace,
            filename=data["name"], body=payload,
        )
    except (binascii.Error, ValueError, TypeError):
        return _error(422, "invalid_web_xlsx_file")
    except (WorkspaceStorageError, AttributeError):
        return _error(503, "web_xlsx_save_unavailable")
    return JSONResponse({
        "ok": True, "contract_version": "claw-web-xlsx-source.v1",
        "file": file, "source": "browser_upload",
        "processing_started": False, "p01_approved": False,
        "drive_uploaded": False,
    }, status_code=201, headers=_NO_STORE)


async def web_xlsx_download(request: Request) -> Response:
    authority = await _authority(request)
    if isinstance(authority, Response):
        return authority
    store, owner, workspace = authority
    doc_id = request.path_params.get("document_id")
    if not isinstance(doc_id, str) or not _ID.fullmatch(doc_id):
        return _error(404, "web_xlsx_not_found")
    try:
        item = await store.get_web_xlsx(
            tenant_id=workspace, owner_id=owner, workspace_id=workspace,
            document_id=doc_id,
        )
    except (WorkspaceStorageError, ValueError, TypeError, AttributeError):
        return _error(503, "web_xlsx_source_unavailable")
    if item is None:
        return _error(404, "web_xlsx_not_found")
    file, payload = item
    return Response(
        payload, media_type=XLSX_MEDIA_TYPE,
        headers={
            **_NO_STORE,
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(file["filename"], safe=""),
            "X-Content-Type-Options": "nosniff",
        },
    )
