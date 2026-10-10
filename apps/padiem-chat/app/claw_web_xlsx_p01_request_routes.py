"""#3580 web XLSX authenticated P01 request dispatch (not approval decision)."""
from __future__ import annotations

import inspect
import json
import re
from datetime import datetime, timedelta, timezone

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .claw_web_xlsx_p01_request import (
    TrustedWebXlsxP01Request, WebXlsxP01RequestError,
    _utc, dispatch_owner_web_xlsx_p01,
)
from .claw_web_xlsx_selection_routes import _scope
from .claw_web_xlsx_source_routes import _error, _NO_STORE

WEB_XLSX_REQUEST_P01_PATH = "/api/claw/office/web-selections/{selection_ref}/request-p01"
_RUN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:@+-]{0,127}$")


async def web_xlsx_request_p01(request: Request) -> Response:
    scope = await _scope(request)
    if isinstance(scope, Response):
        return scope
    original_store, selections, owner, workspace = scope

    # Fail-closed until the private Engine adapter and durable D1 reservation
    # have both been provisioned. No synthetic approval or in-memory fallback.
    client = getattr(request.app.state, "web_xlsx_p01_pause_client", None)
    ledger = getattr(request.app.state, "web_xlsx_p01_request_store", None)
    history = getattr(request.app.state, "history_store", None)
    if (not callable(getattr(client, "start_pause", None))
            or not callable(getattr(ledger, "reserve", None))
            or not callable(getattr(ledger, "commit_pause", None))
            or not callable(getattr(history, "get_claw_run", None))):
        return _error(503, "web_xlsx_p01_unconfigured")
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        return _error(415, "unsupported_media_type")
    try:
        raw = await read_bounded_request_body(request, max_bytes=256)
    except RequestBodyTooLarge:
        return _error(413, "request_too_large")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return _error(400, "invalid_json")
    if not isinstance(data, dict) or set(data) != {"run_id"}:
        return _error(400, "invalid_p01_request_shape")
    run_id = data["run_id"]
    selection_ref = request.path_params.get("selection_ref")
    if type(run_id) is not str or not _RUN.fullmatch(run_id):
        return _error(400, "invalid_run_id")

    try:
        selection = selections.load_owner(
            owner_id=owner, workspace_id=workspace, selection_ref=selection_ref,
        )
        run = history.get_claw_run(owner, run_id)
        if inspect.isawaitable(selection):
            selection = await selection
        if inspect.isawaitable(run):
            run = await run
    except Exception:
        return _error(503, "web_xlsx_p01_owner_lookup_unavailable")
    if (not isinstance(selection, dict) or not isinstance(run, dict)
            or run.get("run_id") != run_id
            or run.get("workspace_id") != workspace
            or run.get("status") != "running"
            or not isinstance(run.get("conversation_id"), str)
            or not run["conversation_id"]):
        return _error(404, "web_xlsx_p01_source_or_run_not_found")
    try:
        # Existing Claw owner run must be recently active, not a historical
        # unrelated approval/closed run that can be recycled by the browser.
        updated = _utc(run["updated_at"])
        now = datetime.now(timezone.utc)
        if not updated <= now < updated + timedelta(minutes=30):
            return _error(404, "web_xlsx_p01_source_or_run_not_found")
        original = await original_store.get_web_xlsx_metadata(
            tenant_id=workspace, owner_id=owner, workspace_id=workspace,
            document_id=selection["document_id"],
        )
    except Exception:
        return _error(503, "web_xlsx_p01_original_unavailable")
    if (not isinstance(original, dict)
            or any(selection.get(k) != original.get(k) for k in
                   ("document_id", "source_sha256", "size_bytes", "filename"))
            or selection.get("status") != "source_selected_p01_not_started"
            or original.get("original_immutable") is not True
            or original.get("processing_authorized") is not False):
        return _error(404, "web_xlsx_p01_source_or_run_not_found")
    try:
        trusted = TrustedWebXlsxP01Request(
            owner_id=owner, workspace_id=workspace, run_id=run_id,
            selection_ref=selection_ref, document_id=original["document_id"],
            source_sha256=original["source_sha256"],
            filename=original["filename"],
            selection_expires_at=selection["expires_at"],
        )
    except (WebXlsxP01RequestError, KeyError, TypeError):
        return _error(404, "web_xlsx_p01_source_or_run_not_found")

    try:
        pending = await dispatch_owner_web_xlsx_p01(
            request=trusted, store=ledger, client=client,
        )
    except WebXlsxP01RequestError:
        return _error(409, "web_xlsx_p01_pause_refused")
    except Exception:
        # Unknown dispatch result: reservation is intentionally NOT released.
        # A retry cannot dispatch the same original to Engine twice.
        return _error(503, "web_xlsx_p01_dispatch_unknown")
    return JSONResponse({
        "ok": True, "contract_version": "web-xlsx-p01-request.v1",
        "request": pending,
    }, status_code=202, headers=_NO_STORE)
