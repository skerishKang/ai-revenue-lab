"""#3932 owner-scoped PDF inline preview; XLSX/DOCX remain download-only.

Only existing canonical workspace artifact IDs are accepted. No local path,
Drive token, new storage authority, or fake XLSX renderer is introduced.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .claw_routes import _resolve_canonical_tenant
from .workspace_storage import WorkspaceStorageAccessError

_ID = re.compile(r"^doc_[A-Za-z0-9]{32}$")
_PDF_MIME = "application/pdf"
_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_MAX_PDF = 10 * 1024 * 1024
_SAFE_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Vary": "Cookie",
}


def _deny(status: int, code: str) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": {"code": code, "message": "파일 미리보기를 사용할 수 없습니다."}},
        status_code=status, headers=_SAFE_HEADERS,
    )


def _preview_document(metadata: Any, content: bytes) -> JSONResponse | Response:
    """Trust neither the metadata's MIME nor a file extension alone."""
    mime = getattr(metadata, "media_type", None)
    filename = getattr(metadata, "filename", "")
    if not isinstance(content, bytes):
        return _deny(503, "artifact_read_invalid")
    if not isinstance(filename, str) or not filename or len(filename) > 160:
        return _deny(503, "artifact_metadata_invalid")
    if mime == _PDF_MIME:
        # Deny mislabeled HTML/malformed/oversized bytes rather than letting a
        # same-origin browser attempt to display user-controlled active content.
        if (not 8 <= len(content) <= _MAX_PDF
                or not content.startswith(b"%PDF-")
                or b"%%EOF" not in content[-1024:]):
            return JSONResponse(
                {"ok": True, "preview": {"available": False, "kind": "download_only",
                                          "reason": "unsupported_pdf", "download_available": True}},
                headers=_SAFE_HEADERS,
            )
        return Response(
            content, status_code=200, media_type=_PDF_MIME,
            headers={**_SAFE_HEADERS,
                     "Content-Disposition": "inline; filename*=UTF-8''" + quote(filename, safe=""),
                     "X-Frame-Options": "SAMEORIGIN",
                     "Content-Length": str(len(content))},
        )
    # This endpoint never claims a rendered spreadsheet based on a ZIP filename.
    # Download is a distinct action on the *existing* owner-scoped byte route.
    reason = "xlsx_preview_not_supported" if mime == _XLSX_MIME else "download_only"
    return JSONResponse(
        {"ok": True, "preview": {"available": False, "kind": "download_only",
                                  "reason": reason, "download_available": True}},
        headers=_SAFE_HEADERS,
    )


async def claw_artifact_inline_preview(request: Request) -> JSONResponse | Response:
    document_id = request.path_params.get("document_id", "")
    if not isinstance(document_id, str) or not _ID.fullmatch(document_id):
        return _deny(400, "invalid_document_id")
    tenant = await _resolve_canonical_tenant(request)
    if tenant is None:
        return _deny(401, "workspace_scope_unavailable")
    store = getattr(request.app.state, "workspace_document_store", None)
    if store is None:
        return _deny(503, "workspace_storage_unavailable")
    try:
        result = await store.get_for_tenant(tenant_id=tenant, document_id=document_id)
    except WorkspaceStorageAccessError:
        return _deny(404, "artifact_not_found")
    except Exception:
        # Do not disclose private object path or foreign-vs-missing hints.
        return _deny(503, "artifact_read_failed")
    if result is None:
        return _deny(404, "artifact_not_found")
    try:
        metadata, data = result
        if getattr(metadata, "document_id", None) != document_id:
            return _deny(503, "artifact_metadata_invalid")
        if getattr(metadata, "tenant_id", None) != tenant:
            return _deny(404, "artifact_not_found")
        return _preview_document(metadata, data)
    except (TypeError, ValueError):
        return _deny(503, "artifact_metadata_invalid")
