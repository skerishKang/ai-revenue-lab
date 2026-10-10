"""#3580 authenticated browser owner approve/deny, exact Engine Tool continuation."""
from __future__ import annotations

import inspect
import json
from datetime import datetime, timedelta, timezone

from starlette.requests import Request
from starlette.responses import Response, JSONResponse

from kagent.p01_approval_continuation import (
    P01AdapterError, build_first_party_decision_submission,
)

from .bounded_request_body import read_bounded_request_body, RequestBodyTooLarge
from .claw_web_xlsx_selection_routes import _scope
from .claw_web_xlsx_source_routes import _error, _NO_STORE
from .claw_web_xlsx_p01_request import _utc, WebXlsxP01RequestError
from .claw_web_xlsx_p01_owner_decision import dispatch_owner_decision

WEB_XLSX_P01_OWNER_DECISION_PATH = (
    "/api/claw/office/web-selections/{selection_ref}/p01-decision"
)


async def web_xlsx_p01_owner_decision(request: Request) -> Response:
    scope = await _scope(request)
    if isinstance(scope, Response):
        return scope
    original_store, selections, owner, workspace = scope

    ledger = getattr(request.app.state, "web_xlsx_p01_owner_decision_store", None)
    client = getattr(request.app.state, "web_xlsx_p01_owner_decision_client", None)
    history = getattr(request.app.state, "history_store", None)
    if (not callable(getattr(ledger, "load_waiting", None))
            or not callable(getattr(ledger, "reserve", None))
            or not callable(getattr(ledger, "commit", None))
            or not callable(getattr(client, "resume_owner_decision", None))
            or not callable(getattr(history, "get_claw_run", None))):
        return _error(503, "web_xlsx_p01_decision_unconfigured")
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        return _error(415, "unsupported_media_type")
    try:
        raw = await read_bounded_request_body(request, max_bytes=128)
    except RequestBodyTooLarge:
        return _error(413, "decision_request_too_large")
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return _error(400, "invalid_json")
    if not isinstance(parsed, dict) or set(parsed) != {"decision"} or parsed.get("decision") not in ("approve", "deny"):
        return _error(400, "invalid_owner_decision")
    selection_ref = request.path_params.get("selection_ref")
    outcome = parsed["decision"]
    try:
        waiting = await ledger.load_waiting(
            owner_id=owner, workspace_id=workspace, selection_ref=selection_ref,
        )
    except Exception:
        return _error(503, "owner_decision_ledger_unavailable")
    if waiting is None:
        return _error(404, "owner_p01_pause_not_found")
    # Re-read both independently owner-scoped B62 source and ongoing run,
    # never treating browser continuation/ref/tool data as authority.
    try:
        selected = selections.load_owner(
            owner_id=owner, workspace_id=workspace, selection_ref=selection_ref,
        )
        run = history.get_claw_run(owner, waiting["run_id"])
        selected = await selected if inspect.isawaitable(selected) else selected
        run = await run if inspect.isawaitable(run) else run
        original = await original_store.get_web_xlsx_metadata(
            tenant_id=workspace, owner_id=owner, workspace_id=workspace,
            document_id=waiting["document_id"],
        )
    except Exception:
        return _error(503, "owner_decision_source_lookup_unavailable")
    now = datetime.now(timezone.utc)
    try:
        live = (
            isinstance(selected, dict) and isinstance(run, dict)
            and isinstance(original, dict)
            and run.get("run_id") == waiting["run_id"]
            and run.get("workspace_id") == workspace
            and run.get("status") == "running"
            and isinstance(run.get("conversation_id"), str)
            and bool(run["conversation_id"])
            and _utc(run["updated_at"]) <= now
            and _utc(run["updated_at"]) + timedelta(minutes=30) > now
            and selected.get("status") == "source_selected_p01_not_started"
            and selected.get("document_id") == waiting["document_id"]
            and selected.get("source_sha256") == waiting["source_sha256"]
            and original.get("document_id") == waiting["document_id"]
            and original.get("source_sha256") == waiting["source_sha256"]
            and original.get("original_immutable") is True
            and original.get("processing_authorized") is False
            and selected.get("filename") == original.get("filename")
            and selected.get("size_bytes") == original.get("size_bytes")
        )
    except (WebXlsxP01RequestError, KeyError, TypeError, ValueError):
        live = False
    if not live:
        return _error(404, "owner_p01_source_or_run_not_found")
    try:
        verified = await dispatch_owner_decision(
            waiting=waiting, outcome=outcome, store=ledger, client=client,
            submission_factory=build_first_party_decision_submission,
        )
    except P01AdapterError:
        return _error(409, "owner_p01_decision_unusable")
    except WebXlsxP01RequestError:
        return _error(409, "owner_p01_decision_unconfirmed")
    except Exception:
        # Ambiguous Engine result: preserve one-shot D1 reservation. No retry.
        return _error(503, "owner_p01_decision_dispatch_unknown")
    return JSONResponse({
        "ok": True, "contract_version": "claw-web-xlsx-p01-owner-decision.v1",
        "selection_ref": selection_ref,
        "status": verified, "processing_started": False,
        "workcopy_created": False, "owner_intent_only": True,
    }, status_code=200, headers=_NO_STORE)
