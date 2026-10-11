"""Hark WEB-FIRST: owner-approved workcopy quote edit *preview* only.

This route intentionally has no XLSX mutation, WRITE grant, or PDF output.
The existing owner+P01 download gate is reused for original bytes; user
input cannot specify an R2 key, workcopy id, grant or Engine continuation.
"""
from __future__ import annotations

import hashlib
import json
import re

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .bounded_request_body import read_bounded_request_body, RequestBodyTooLarge
from .claw_web_xlsx_p01_owner_decision_routes import web_xlsx_p01_workcopy_download
from .claw_web_xlsx_source_routes import _error, _NO_STORE
from .claw_web_xlsx_quote_write_pause_store import D1WebQuoteWritePauseStore
from .claw_web_xlsx_quote_write_owner_decision import D1WebQuoteWriteOwnerDecisionStore
from .claw_web_xlsx_quote_editor import (
    revise_single_sheet_quote, WebQuoteEditUnsupported,
)

WEB_XLSX_QUOTE_PREVIEW_PATH = (
    "/api/claw/office/web-selections/{selection_ref}/quote-edit/preview"
)
_PREVIEW_TYPE = "claw-web-xlsx-quote-edit-preview.v1"
_ID = re.compile(r"^sel_[0-9a-f]{32}$")


async def web_xlsx_quote_edit_preview(request: Request) -> Response:
    """Show exactly what a later independent P01 WRITE would authorize."""
    ref = request.path_params.get("selection_ref")
    if type(ref) is not str or not _ID.fullmatch(ref):
        return _error(404, "owner_approved_workcopy_not_found")
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        return _error(415, "unsupported_media_type")
    try:
        raw = await read_bounded_request_body(request, max_bytes=512)
    except RequestBodyTooLarge:
        return _error(413, "quote_edit_preview_too_large")
    try:
        values = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return _error(400, "quote_edit_preview_bad_json")
    if (type(values) is not dict or set(values) != {"school_name", "supply_amount"}
            or type(values["school_name"]) is not str
            or type(values["supply_amount"]) is not int):
        return _error(400, "quote_edit_preview_invalid_fields")
    # All of the existing P01 approval + owner D1 + R2 SHA checks must pass
    # before we read even one workbook byte.
    protected = await web_xlsx_p01_workcopy_download(request)
    if protected.status_code != 200:
        return protected
    content = protected.body
    if type(content) is not bytes or not 1 <= len(content) <= 1_048_576:
        return _error(503, "approved_workcopy_preview_invalid")
    sha = hashlib.sha256(content).hexdigest()
    try:
        revision = revise_single_sheet_quote(
            original=content, original_sha256=sha,
            school_name=values["school_name"],
            supply_amount=values["supply_amount"],
        )
    except WebQuoteEditUnsupported:
        return _error(422, "quote_edit_unsupported_template_or_values")

    # This exact canonical JSON is also hashed inside the separately
    # write-gated WorkspaceDocumentStore.create_authorized_web_quote_revision.
    edit_contract = json.dumps(
        {"school_name": values["school_name"],
         "supply_amount": values["supply_amount"],
         "output_formats": ["xlsx"], "overwrite_original": False},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    edit_sha = hashlib.sha256(edit_contract.encode("utf-8")).hexdigest()
    return JSONResponse({
        "ok": True,
        "contract_version": _PREVIEW_TYPE,
        "selection_ref": ref,
        "original_workcopy_sha256": revision.source_sha256,
        "edit_sha256": edit_sha,
        "revision_preview_sha256": revision.revised_sha256,
        "school_name": revision.requested_school_name,
        "supply_amount": revision.requested_supply_amount,
        "vat_amount": revision.vat_amount,
        "total_amount": revision.total_amount,
        "preview_only": True,
        "write_approved": False,
        "revised_xlsx_created": False,
        "pdf_exported": False,
        "pdf_unsupported": True,
        "requires_independent_p01_write": True,
        "write_request_available": (
            getattr(request.app.state, "web_xlsx_quote_write_enabled", False)
            is True
            and callable(getattr(
                getattr(request.app.state, "web_xlsx_quote_write_client", None),
                "start_pause", None))
            and callable(getattr(
                getattr(request.app.state, "web_xlsx_quote_write_client", None),
                "resume_owner_decision", None))
            and isinstance(getattr(
                request.app.state, "web_xlsx_quote_write_pause_store", None),
                D1WebQuoteWritePauseStore)
            and isinstance(getattr(
                request.app.state, "web_xlsx_quote_write_owner_decision_store", None),
                D1WebQuoteWriteOwnerDecisionStore)
            and getattr(request.app.state, "web_xlsx_quote_write_store", None)
            is not None
        ),
    }, headers={**_NO_STORE, "Vary": "Cookie",
                "Cross-Origin-Resource-Policy": "same-origin"})
