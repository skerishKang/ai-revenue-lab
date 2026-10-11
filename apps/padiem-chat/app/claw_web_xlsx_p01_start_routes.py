"""#3580 WEB-FIRST: mint an owner-bound P01 request from a browser selection.

No caller-provided run_id, owner, source digest, Engine tool or approval grant.
This endpoint does not read the XLSX bytes and never retries uncertain dispatch.
"""
from __future__ import annotations

import inspect
import json

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .claw_web_xlsx_p01_request import (
    TrustedWebXlsxP01Request, WebXlsxP01RequestError,
    dispatch_owner_web_xlsx_p01,
)
from .claw_web_xlsx_selection_routes import _scope
from .claw_web_xlsx_source_routes import _error, _NO_STORE

WEB_XLSX_START_P01_PATH = "/api/claw/office/web-selections/{selection_ref}/start-p01"


async def web_xlsx_start_p01(request: Request) -> Response:
    scope = await _scope(request)
    if isinstance(scope, Response):
        return scope
    original_store, selections, owner, workspace = scope
    client = getattr(request.app.state, "web_xlsx_p01_pause_client", None)
    ledger = getattr(request.app.state, "web_xlsx_p01_request_store", None)
    history = getattr(request.app.state, "history_store", None)
    if (not callable(getattr(client, "start_pause", None))
            or not callable(getattr(ledger, "reserve", None))
            or not callable(getattr(ledger, "commit_pause", None))
            or not callable(getattr(ledger, "preflight_start", None))
            or not callable(getattr(history, "create_web_xlsx_p01_run", None))
            or not callable(getattr(history, "get_claw_run", None))):
        return _error(503, "web_xlsx_p01_start_unconfigured")
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        return _error(415, "unsupported_media_type")
    try:
        raw = await read_bounded_request_body(request, max_bytes=32)
    except RequestBodyTooLarge:
        return _error(413, "request_too_large")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return _error(400, "invalid_json")
    # An empty object is deliberate: no user-supplied run, conversation, or tool.
    if type(data) is not dict or data:
        return _error(400, "invalid_p01_start_shape")
    selection_ref = request.path_params.get("selection_ref")

    try:
        selected = selections.load_owner(
            owner_id=owner, workspace_id=workspace, selection_ref=selection_ref,
        )
        if inspect.isawaitable(selected):
            selected = await selected
        if not isinstance(selected, dict) or selected.get("status") != "source_selected_p01_not_started":
            return _error(404, "web_xlsx_p01_source_not_found")
        original = await original_store.get_web_xlsx_metadata(
            tenant_id=workspace, owner_id=owner, workspace_id=workspace,
            document_id=selected["document_id"],
        )
        if (not isinstance(original, dict)
                or any(selected.get(k) != original.get(k) for k in
                       ("document_id", "source_sha256", "size_bytes", "filename"))
                or original.get("original_immutable") is not True
                or original.get("processing_authorized") is not False):
            return _error(404, "web_xlsx_p01_source_not_found")

        # Validate unexpired source and D1 schema BEFORE creating a new run.
        # Concurrent starts are still serialized by the unique request D1 key.
        template = dict(
            owner_id=owner, workspace_id=workspace, run_id="web_p01_preflight",
            selection_ref=selection_ref, document_id=original["document_id"],
            source_sha256=original["source_sha256"],
            filename=original["filename"],
            selection_expires_at=selected["expires_at"],
        )
        TrustedWebXlsxP01Request(**template)
        unused = ledger.preflight_start(
            owner_id=owner, workspace_id=workspace, selection_ref=selection_ref,
        )
        if inspect.isawaitable(unused):
            unused = await unused
        if unused is not True:
            return _error(409, "web_xlsx_p01_already_requested")
    except WebXlsxP01RequestError:
        return _error(404, "web_xlsx_p01_source_not_found")
    except Exception:
        return _error(503, "web_xlsx_p01_start_lookup_unavailable")

    try:
        # Run/conversation minted and persisted by trusted B62 history only.
        # No model call, fake user message, or caller-selected conversation.
        created = history.create_web_xlsx_p01_run(
            user_id=owner, workspace_id=workspace, filename=original["filename"],
        )
        run_id = await created if inspect.isawaitable(created) else created
        run = history.get_claw_run(owner, run_id)
        if inspect.isawaitable(run):
            run = await run
        if (not isinstance(run, dict)
                or run.get("run_id") != run_id
                or run.get("workspace_id") != workspace
                or run.get("status") != "running"
                or not isinstance(run.get("conversation_id"), str)
                or not run["conversation_id"]):
            return _error(503, "web_xlsx_p01_start_run_unavailable")
        trusted = TrustedWebXlsxP01Request(**{**template, "run_id": run_id})
    except Exception:
        return _error(503, "web_xlsx_p01_start_run_unavailable")
    try:
        pending = await dispatch_owner_web_xlsx_p01(
            request=trusted, store=ledger, client=client,
        )
    except WebXlsxP01RequestError:
        return _error(409, "web_xlsx_p01_pause_refused")
    except Exception:
        # Preserve uncertain reservation; browser must GET status, never retry POST.
        return _error(503, "web_xlsx_p01_dispatch_unknown")
    return JSONResponse({
        "ok": True, "contract_version": "claw-web-xlsx-p01-start.v1",
        "selection_ref": selection_ref, "status": pending["status"],
        "processing_started": False, "workcopy_created": False,
    }, status_code=202, headers=_NO_STORE)
