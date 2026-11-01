"""#3180 ③ — an owner's own PC Excel form, registered as their saved quote form.

A form the owner already uses only becomes repeatable if Padiem remembers it. The
original workbook stays on the owner's PC: this module reads it once (the same
finished PC read the fill used), asks the COM2 file lane to describe its cells,
and stores that description plus the PC-side path reference in the EXISTING
saved-quote asset table (`b66_saved_quote_skill`, kind `pc_form`). No second
store, no second list route, and no workbook bytes are kept.

Repeat use then reads the workbook from the PC again by that stored path, so a
form the owner edits on their own machine keeps working without re-registering.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id
from .b66_pc_template_routes import _cli, _lane_json, _lane_upload
from .b66_saved_quote_skill_store import (
    SKILL_KIND_PC_FORM,
    SavedQuoteSkillStoreError,
    build_pc_form_artifact,
)
from .bounded_request_body import read_bounded_request_body, RequestBodyTooLarge
from .claw_memory_routes import _resolve_memory_workspace
from .pc_file_exchange_routes import DISPATCH_ID, _dispatch_row, _stored_output

PC_QUOTE_FORMS_PATH = "/api/b66/pc-quote/forms"
MAX_FORM_REQUEST_BYTES = 4 * 1024
_BODY_KEYS = frozenset({"file_id", "name", "mapping", "analyze_only"})
_NAME_MAX = 80


def _error(status: int, code: str) -> JSONResponse:
    return JSONResponse({"ok": False, "error": {"code": code}}, status_code=status,
                        headers={"Cache-Control": "no-store, max-age=0"})


def _name(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    if not text or len(text) > _NAME_MAX or any(ord(ch) < 32 for ch in text):
        return None
    return text


def _mint_skill_id() -> str:
    return "pcform_" + uuid.uuid4().hex


async def pc_quote_form_register(request: Request) -> JSONResponse:
    """Register one finished PC read's workbook as the owner's saved quote form."""

    uid = current_user_id(request) if auth_ready(request) else None
    if not isinstance(uid, str) or not uid:
        return _error(401, "unauthorized")
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        return _error(415, "unsupported_media_type")
    try:
        raw = await read_bounded_request_body(request, max_bytes=MAX_FORM_REQUEST_BYTES)
    except RequestBodyTooLarge:
        return _error(413, "request_too_large")
    try:
        body = json.loads(raw.decode("utf-8")) if raw else None
    except (UnicodeDecodeError, ValueError):
        return _error(400, "invalid_json")
    if not isinstance(body, dict) or set(body) - _BODY_KEYS:
        return _error(400, "unsupported_field")
    file_id = body.get("file_id")
    if not isinstance(file_id, str) or DISPATCH_ID.fullmatch(file_id) is None:
        return _error(422, "pc_dispatch_not_found")
    name = _name(body.get("name"))
    if name is None:
        return _error(422, "form_name_invalid")

    store = getattr(request.app.state, "b66_saved_quote_skill_store", None)
    if not callable(getattr(store, "put_approved_skill", None)):
        return _error(503, "saved_quote_skill_unavailable")

    dispatch = await _dispatch_row(request, uid, file_id)
    if isinstance(dispatch, JSONResponse):
        return dispatch
    if dispatch.get("state") != "done":
        return _error(409, "pc_dispatch_not_ready")
    data, refusal = await _stored_output(request, uid, dispatch)
    if refusal is not None:
        return refusal
    if not isinstance(data, bytes) or not data:
        return _error(404, "pc_dispatch_not_found")

    # The PC-side location, relative to the granted root the read used. It names
    # no absolute machine path and is only ever resolved again through that root.
    path = str(dispatch.get("file_path") or "").replace("\\", "/").strip()
    filename = path.rsplit("/", 1)[-1] if path else ""
    if not path or not filename.lower().endswith(".xlsx"):
        return _error(422, "form_path_invalid")

    client = _cli(request)
    if client is None or getattr(client, "ready", False) is not True:
        return _error(503, "file_lane_unavailable")
    lane_id = await _lane_upload(client, uid, filename, data)
    if lane_id is None:
        return _error(502, "file_lane_unavailable")
    structure = await _lane_json(client, uid, method="GET", path="/files/" + lane_id + "/structure")
    if not isinstance(structure, dict) or not isinstance(structure.get("sheets"), list):
        return _error(502, "form_structure_failed")

    if body.get("analyze_only") is True:
        from .b66_quote_form_analysis import analyze_quote_form
        return JSONResponse(
            {"ok": True, "analysis": analyze_quote_form(structure)},
            headers={"Cache-Control": "no-store, max-age=0"},
        )
    if "analyze_only" in body and body["analyze_only"] is not False:
        return _error(400, "unsupported_field")

    workspace_id = await _resolve_memory_workspace(request, uid)
    if not isinstance(workspace_id, str) or not workspace_id:
        return _error(503, "workspace_unavailable")
    try:
        artifact = build_pc_form_artifact(
            skill_id=_mint_skill_id(),
            skill_name=name,
            form={
                "path": path,
                "filename": filename,
                "structure": {"sheets": structure["sheets"]},
                # The item-row pattern is learned later, on the first fill from
                # this saved form; registration itself adds no rows.
                "item_rows": [],
                **({"mapping": body["mapping"]} if "mapping" in body else {}),
            },
            approved_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        )
    except SavedQuoteSkillStoreError:
        return _error(422, "form_invalid")
    try:
        stored = store.put_approved_skill(
            user_id=uid, workspace_id=workspace_id, artifact=artifact,
        )
        if hasattr(stored, "__await__"):
            stored = await stored
    except SavedQuoteSkillStoreError:
        return _error(422, "form_invalid")
    except Exception:
        return _error(503, "form_write_failed")
    if not isinstance(stored, dict) or not stored.get("saved_skill_id"):
        return _error(503, "form_write_failed")

    return JSONResponse(
        {
            "ok": True,
            "form": {
                "saved_skill_id": stored["saved_skill_id"],
                "skill_id": stored.get("skill_id"),
                "skill_name": stored.get("skill_name") or name,
                "skill_kind": SKILL_KIND_PC_FORM,
                "form_path": path,
                "form_filename": filename,
                "sheet_count": len(structure["sheets"]),
            },
        },
        headers={"Cache-Control": "no-store, max-age=0"},
    )
