"""Owner-bound B62 XLSX selection, explicitly NOT an Engine approval."""
from __future__ import annotations

import json
import re

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .claw_web_xlsx_source_routes import _authority, _error, _NO_STORE
from .claw_web_xlsx_selection_store import WebXlsxSelectionError

WEB_SELECTIONS_PATH = "/api/claw/office/web-selections"
WEB_SELECTION_PATH = "/api/claw/office/web-selections/{selection_ref}"
_DOC = re.compile(r"^doc_[0-9a-f]{32}$")


async def _scope(request: Request):
    authority = await _authority(request)
    if isinstance(authority, Response):
        return authority
    source_store, owner, workspace = authority
    selections = getattr(request.app.state, "claw_web_xlsx_selection_store", None)
    if selections is None:
        return _error(503, "web_xlsx_selection_unavailable")
    return source_store, selections, owner, workspace


async def web_xlsx_selections(request: Request) -> Response:
    scope = await _scope(request)
    if isinstance(scope, Response):
        return scope
    source_store, selections, owner, workspace = scope
    if request.method == "GET":
        try:
            rows = await selections.list_owner(owner_id=owner, workspace_id=workspace)
        except Exception:
            return _error(503, "web_xlsx_selection_unavailable")
        return JSONResponse({
            "ok": True, "contract_version": "claw-web-xlsx-selection.v1",
            "selections": rows, "p01_approval_started": False,
            "processing_started": False,
        }, headers=_NO_STORE)
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        return _error(415, "unsupported_media_type")
    try:
        body = await read_bounded_request_body(request, max_bytes=256)
    except RequestBodyTooLarge:
        return _error(413, "web_xlsx_selection_request_too_large")
    try:
        data = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return _error(400, "invalid_json")
    if not isinstance(data, dict) or set(data) != {"document_id"}:
        return _error(400, "invalid_web_xlsx_selection_shape")
    doc_id = data["document_id"]
    if type(doc_id) is not str or not _DOC.fullmatch(doc_id):
        return _error(400, "invalid_web_xlsx_document_id")
    try:
        # Metadata lookup only. Never read R2 bytes at selection time.
        original = await source_store.get_web_xlsx_metadata(
            tenant_id=workspace, owner_id=owner, workspace_id=workspace,
            document_id=doc_id,
        )
    except Exception:
        return _error(503, "web_xlsx_original_metadata_unavailable")
    if original is None:
        return _error(404, "web_xlsx_original_not_found")
    try:
        selected = await selections.select(
            owner_id=owner, workspace_id=workspace, source=original,
        )
    except WebXlsxSelectionError:
        return _error(409, "web_xlsx_selection_refused")
    except Exception:
        return _error(503, "web_xlsx_selection_unavailable")
    return JSONResponse({
        "ok": True, "contract_version": "claw-web-xlsx-selection.v1",
        "selection": selected, "p01_approval_started": False,
        "processing_started": False, "workcopy_created": False,
        "drive_uploaded": False,
    }, status_code=201, headers=_NO_STORE)


async def web_xlsx_selection_detail(request: Request) -> Response:
    scope = await _scope(request)
    if isinstance(scope, Response):
        return scope
    _source_store, selections, owner, workspace = scope
    selection_ref = request.path_params.get("selection_ref")
    try:
        selected = await selections.load_owner(
            owner_id=owner, workspace_id=workspace, selection_ref=selection_ref,
        )
    except Exception:
        return _error(503, "web_xlsx_selection_unavailable")
    if selected is None:
        return _error(404, "web_xlsx_selection_not_found")
    return JSONResponse({
        "ok": True, "contract_version": "claw-web-xlsx-selection.v1",
        "selection": selected, "p01_approval_started": False,
        "processing_started": False,
    }, headers=_NO_STORE)
