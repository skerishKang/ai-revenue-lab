"""#3580 WEB-FIRST: owner-selected original XLSX bytes in private D1/R2.

This is web source intake, not an Engine P01 approval, editing tool, Excel/PDF
converter or Drive WRITE. The original file remains unchanged; the explicit
P01 processing approval will be composed in a separate web milestone.
"""
from __future__ import annotations

import json
import re
from urllib.parse import quote, unquote

from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from .auth_routes import auth_ready, current_user_id
from .bounded_request_body import read_bounded_request_body, RequestBodyTooLarge
from .claw_memory_routes import _resolve_memory_workspace
from .file_lane import AttachmentValidationError
from .workspace_storage import (
    MAX_WEB_XLSX_BYTES, WEB_XLSX_INLINE_MAX_BYTES, WorkspaceStorageError,
    XLSX_MEDIA_TYPE,
)

WEB_SOURCES_PATH = "/api/claw/office/web-sources"
WEB_SOURCE_DOWNLOAD_PATH = "/api/claw/office/web-sources/{document_id}/download"
#: Above the inline limit the browser uploads to the COM2 file lane with this
#: ticket, then registers the resulting file id here. Chat never holds the body.
WEB_SOURCE_UPLOAD_TICKET_PATH = "/api/claw/office/web-sources/upload-ticket"
WEB_SOURCE_REGISTER_PATH = "/api/claw/office/web-sources/{file_id}/register"
_ID = re.compile(r"^doc_[0-9a-f]{32}$")
_FILE_ID = re.compile(r"^file_[0-9a-f]{32}$")
_NO_STORE = {
    "Cache-Control": "private, no-store, max-age=0",
    "Pragma": "no-cache", "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}
_MAX_BODY = WEB_XLSX_INLINE_MAX_BYTES
_MAX_SMALL_BODY = 2048


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

    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/octet-stream":
        return _error(415, "unsupported_media_type")
    encoded_name = request.headers.get("x-padiem-filename")
    if not encoded_name or len(encoded_name) > 512:
        return _error(400, "invalid_web_xlsx_shape")
    try:
        filename = unquote(encoded_name, encoding="utf-8", errors="strict")
        # A raw byte request avoids a Base64 intermediary and JSON decoding.
        payload = await read_bounded_request_body(request, max_bytes=_MAX_BODY)
        if not payload:
            return _error(422, "invalid_web_xlsx_payload")
        file = await store.put_web_xlsx(
            tenant_id=workspace, owner_id=owner, workspace_id=workspace,
            filename=filename, body=payload,
        )
    except RequestBodyTooLarge:
        return _error(413, "web_xlsx_too_large")
    except (ValueError, TypeError, UnicodeError):
        return _error(422, "invalid_web_xlsx_file")
    except (WorkspaceStorageError, AttributeError):
        return _error(503, "web_xlsx_save_unavailable")
    return JSONResponse({
        "ok": True, "contract_version": "claw-web-xlsx-source.v1",
        "file": file, "source": "browser_upload",
        "processing_started": False, "p01_approved": False,
        "drive_uploaded": False,
    }, status_code=201, headers=_NO_STORE)


def _file_lane(request: Request):
    client = getattr(request.app.state, "file_lane_client", None)
    return client if client is not None and client.ready else None


def _disposition(filename: str) -> dict[str, str]:
    return {
        **_NO_STORE,
        "Content-Disposition": "attachment; filename*=UTF-8''" + quote(filename, safe=""),
        "X-Content-Type-Options": "nosniff",
    }


async def web_xlsx_upload_ticket(request: Request) -> Response:
    """Mint one owner-scoped lane ticket for an original larger than Chat holds.

    The body is a size claim only; nothing is stored and no document row exists
    until the browser registers the lane's resulting file id.
    """
    authority = await _authority(request)
    if isinstance(authority, Response):
        return authority
    _, owner, _ = authority
    client = _file_lane(request)
    if client is None:
        return _error(503, "file_lane_unavailable")
    try:
        raw = json.loads(await read_bounded_request_body(request, max_bytes=_MAX_SMALL_BODY))
        if (not isinstance(raw, dict) or set(raw) != {"size_bytes"}
                or type(raw["size_bytes"]) is not int):
            raise ValueError("invalid size")
    except RequestBodyTooLarge:
        return _error(413, "web_xlsx_too_large")
    except (ValueError, TypeError, UnicodeError):
        return _error(422, "invalid_request")
    if raw["size_bytes"] <= 0:
        return _error(422, "invalid_request")
    if raw["size_bytes"] > MAX_WEB_XLSX_BYTES:
        return _error(413, "web_xlsx_too_large")
    try:
        ticket = client.upload_ticket(owner, raw["size_bytes"])
    except AttachmentValidationError:
        return _error(503, "file_lane_unavailable")
    return JSONResponse({
        **ticket,
        "contract_version": "claw-web-xlsx-upload-ticket.v1",
        "register_path": WEB_SOURCE_REGISTER_PATH,
        "contract_max_bytes": MAX_WEB_XLSX_BYTES,
    }, headers=_NO_STORE)


async def web_xlsx_register(request: Request) -> Response:
    """Link one lane-stored original to a new owner-scoped document row.

    Owner, workspace, digest and size come from the lane's own metadata, so a
    caller can only register a file it uploaded, under the identity this
    deployment already verified for that file.
    """
    authority = await _authority(request)
    if isinstance(authority, Response):
        return authority
    store, owner, workspace = authority
    file_id = request.path_params.get("file_id")
    if not isinstance(file_id, str) or not _FILE_ID.fullmatch(file_id):
        return _error(404, "web_xlsx_not_found")
    client = _file_lane(request)
    if client is None:
        return _error(503, "file_lane_unavailable")
    try:
        meta = await client.meta(owner, file_id)
    except AttachmentValidationError:
        return _error(404, "web_xlsx_not_found")
    if meta["kind"] != "xlsx":
        return _error(422, "invalid_web_xlsx_file")
    if meta["size_bytes"] > MAX_WEB_XLSX_BYTES:
        return _error(413, "web_xlsx_too_large")
    try:
        file = await store.put_web_xlsx_reference(
            tenant_id=workspace, owner_id=owner, workspace_id=workspace,
            filename=meta["name"], file_id=file_id,
            source_sha256=meta["sha256"], size_bytes=meta["size_bytes"],
        )
    except (ValueError, TypeError):
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
        file = await store.get_web_xlsx_metadata(
            tenant_id=workspace, owner_id=owner, workspace_id=workspace,
            document_id=doc_id,
        )
    except (WorkspaceStorageError, ValueError, TypeError, AttributeError):
        return _error(503, "web_xlsx_source_unavailable")
    if file is None:
        return _error(404, "web_xlsx_not_found")
    lane_file_id = file.get("file_id")
    if lane_file_id is not None:
        return await _download_from_file_lane(request, owner, file, lane_file_id)
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
    return Response(payload, media_type=XLSX_MEDIA_TYPE, headers=_disposition(file["filename"]))


async def _download_from_file_lane(request: Request, owner: str, file: dict, file_id: str) -> Response:
    """Stream the lane's original without this process holding the full body."""
    client = _file_lane(request)
    if client is None:
        return _error(503, "file_lane_unavailable")
    try:
        meta = await client.meta(owner, file_id)
        if (meta["sha256"] != file["source_sha256"]
                or meta["size_bytes"] != file["size_bytes"]):
            return _error(503, "web_xlsx_source_unavailable")
        stream = client.open_raw(owner, file_id)
        upstream = await stream.__aenter__()
    except AttachmentValidationError:
        return _error(503, "web_xlsx_source_unavailable")
    if upstream.status_code != 200:
        await stream.__aexit__(None, None, None)
        return _error(404 if upstream.status_code == 404 else 503, "web_xlsx_not_found")

    async def body():
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await stream.__aexit__(None, None, None)

    headers = _disposition(file["filename"])
    headers["Content-Length"] = str(file["size_bytes"])
    return StreamingResponse(body(), media_type=XLSX_MEDIA_TYPE, headers=headers)
