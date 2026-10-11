"""#3580 authenticated browser owner approve/deny, exact Engine Tool continuation."""
from __future__ import annotations

import hashlib
import inspect
import json
import re
from urllib.parse import quote
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
WEB_XLSX_P01_OWNER_STATUS_PATH = (
    "/api/claw/office/web-selections/{selection_ref}/p01-status"
)
WEB_XLSX_P01_WORKCOPY_DOWNLOAD_PATH = (
    "/api/claw/office/web-selections/{selection_ref}/workcopy/download"
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
    # The opt-in is set exclusively by the Worker composition root. A
    # browser approval decision or a D1 "confirmed" row is never itself a
    # processing grant; only the authenticated Engine ToolRuntime completion
    # with its exact source SHA can enter this callback.
    copy_enabled = (
        getattr(request.app.state, "web_xlsx_p01_workcopy_after_grant_enabled", False)
        is True and outcome == "approve"
    )
    if (copy_enabled
            and not callable(getattr(original_store, "create_approved_web_xlsx_workcopy", None))):
        return _error(503, "approved_workcopy_storage_unavailable")

    async def _approved_workcopy(*, waiting, verified_source_sha256):
        if (verified_source_sha256 != waiting["source_sha256"]
                or waiting["user_id"] != owner
                or waiting["workspace_id"] != workspace):
            raise WebXlsxP01RequestError("approved workcopy scope mismatch")

        async def _verified_grant(**scope):
            # The one-shot trusted Engine response is scoped to this
            # already-confirmed owner D1 run/source, not a bearer token.
            return (
                scope.get("owner_id") == owner
                and scope.get("workspace_id") == workspace
                and scope.get("run_id") == waiting["run_id"]
                and scope.get("document_id") == waiting["document_id"]
                and scope.get("source_sha256") == verified_source_sha256
                and scope.get("operation") == "read_for_workcopy"
                and set(scope) == {
                    "owner_id", "workspace_id", "run_id", "document_id",
                    "source_sha256", "operation",
                }
            )

        return await original_store.create_approved_web_xlsx_workcopy(
            tenant_id=workspace, owner_id=owner, workspace_id=workspace,
            source_document_id=waiting["document_id"],
            expected_source_sha256=verified_source_sha256,
            run_id=waiting["run_id"], grant_verifier=_verified_grant,
        )

    try:
        decision_result = await dispatch_owner_decision(
            waiting=waiting, outcome=outcome, store=ledger, client=client,
            submission_factory=build_first_party_decision_submission,
            approved_workcopy_handler=_approved_workcopy if copy_enabled else None,
        )
    except P01AdapterError:
        return _error(409, "owner_p01_decision_unusable")
    except WebXlsxP01RequestError:
        return _error(409, "owner_p01_decision_or_workcopy_unconfirmed")
    except Exception:
        # Ambiguous Engine result: preserve one-shot D1 reservation. No retry.
        return _error(503, "owner_p01_decision_dispatch_unknown")
    verified, copy = (
        decision_result if isinstance(decision_result, tuple)
        else (decision_result, None)
    )
    return JSONResponse({
        "ok": True, "contract_version": "claw-web-xlsx-p01-owner-decision.v1",
        "selection_ref": selection_ref,
        "status": verified, "processing_started": copy is not None,
        "workcopy_created": copy is not None,
        "workcopy_document_id": copy["workcopy_document_id"] if copy else None,
        "owner_intent_only": copy is None,
    }, status_code=200, headers=_NO_STORE)


async def web_xlsx_p01_owner_status(request: Request) -> Response:
    """Authenticated metadata-only UI state; no pause IDs or grant evidence."""
    scope = await _scope(request)
    if isinstance(scope, Response):
        return scope
    original_store, _selections, owner, workspace = scope
    ledger = getattr(request.app.state, "web_xlsx_p01_owner_decision_store", None)
    client = getattr(request.app.state, "web_xlsx_p01_owner_decision_client", None)
    history = getattr(request.app.state, "history_store", None)
    if not callable(getattr(ledger, "load_status", None)):
        return _error(503, "web_xlsx_p01_status_unconfigured")
    selection_ref = request.path_params.get("selection_ref")
    try:
        state = await ledger.load_status(
            owner_id=owner, workspace_id=workspace, selection_ref=selection_ref,
        )
    except Exception:
        return _error(503, "web_xlsx_p01_status_unavailable")
    if state is None:
        return _error(404, "owner_p01_selection_not_found")

    # Never show an actionable confirmation unless the Engine-issued pause,
    # the user-owned run AND the same immutable original are still available.
    actionable = False
    if state["status"] == "waiting_p01":
        try:
            waiting = await ledger.load_waiting(
                owner_id=owner, workspace_id=workspace,
                selection_ref=selection_ref,
            )
            original = await original_store.get_web_xlsx_metadata(
                tenant_id=workspace, owner_id=owner, workspace_id=workspace,
                document_id=state["document_id"],
            )
            run = None
            if waiting and callable(getattr(history, "get_claw_run", None)):
                run = history.get_claw_run(owner, waiting["run_id"])
                if inspect.isawaitable(run):
                    run = await run
            now = datetime.now(timezone.utc)
            actionable = bool(
                waiting and isinstance(original, dict) and isinstance(run, dict)
                and run.get("run_id") == waiting["run_id"]
                and run.get("workspace_id") == workspace
                and run.get("status") == "running"
                and isinstance(run.get("conversation_id"), str)
                and bool(run["conversation_id"])
                and _utc(run["updated_at"]) <= now
                and _utc(run["updated_at"]) + timedelta(minutes=30) > now
                and original.get("document_id") == state["document_id"]
                and original.get("source_sha256") == state["source_sha256"]
                and original.get("filename") == state["filename"]
                and original.get("size_bytes") == state["size_bytes"]
                and original.get("original_immutable") is True
                and original.get("processing_authorized") is False
            )
        except Exception:
            # Database outages and ambiguous status never create browser grants.
            return _error(503, "web_xlsx_p01_status_authority_unavailable")
        if not actionable:
            state["status"] = "manual_review"

    ready = bool(
        actionable and callable(getattr(client, "resume_owner_decision", None))
        and callable(getattr(ledger, "reserve", None))
        and callable(getattr(ledger, "commit", None))
    )
    # File-selected, no pause yet: expose a server-calculated REQUEST ability,
    # not a browser-granted Engine approval or a user-controlled run ID.
    request_ready = False
    if state["status"] == "not_requested":
        pause_client = getattr(request.app.state, "web_xlsx_p01_pause_client", None)
        request_store = getattr(request.app.state, "web_xlsx_p01_request_store", None)
        if (callable(getattr(pause_client, "start_pause", None))
                and callable(getattr(request_store, "preflight_start", None))
                and callable(getattr(request_store, "reserve", None))
                and callable(getattr(request_store, "commit_pause", None))
                and callable(getattr(history, "create_web_xlsx_p01_run", None))):
            try:
                original = await original_store.get_web_xlsx_metadata(
                    tenant_id=workspace, owner_id=owner, workspace_id=workspace,
                    document_id=state["document_id"],
                )
                unique = request_store.preflight_start(
                    owner_id=owner, workspace_id=workspace,
                    selection_ref=selection_ref,
                )
                if inspect.isawaitable(unique):
                    unique = await unique
                request_ready = bool(
                    unique is True and isinstance(original, dict)
                    and original.get("document_id") == state["document_id"]
                    and original.get("source_sha256") == state["source_sha256"]
                    and original.get("filename") == state["filename"]
                    and original.get("size_bytes") == state["size_bytes"]
                    and original.get("original_immutable") is True
                    and original.get("processing_authorized") is False
                )
            except Exception:
                request_ready = False
    copy = None
    if state["status"] == "confirmed" and state.get("run_id"):
        finder = getattr(original_store, "find_approved_web_xlsx_workcopy", None)
        if callable(finder):
            try:
                copy = await finder(
                    tenant_id=workspace, owner_id=owner, workspace_id=workspace,
                    run_id=state["run_id"], source_document_id=state["document_id"],
                    expected_source_sha256=state["source_sha256"],
                )
            except Exception:
                return _error(503, "approved_workcopy_status_unavailable")
    # #3933 READ handoff: the server-minted owner work conversation for this
    # exact owner/workspace/run, exposed only after the same owner-scoped
    # workcopy receipt above proved the approved copy exists. This is a
    # navigation handle for the owner's own conversation only: never an
    # artifact-index claim, a file READ grant or a WRITE authorization, and
    # the conversation is opened through the existing authenticated loader.
    work_conversation = None
    if (copy is not None
            and isinstance(state.get("run_id"), str)
            and callable(getattr(history, "get_claw_run", None))
            and callable(getattr(history, "verify_owner_conversation_artifacts", None))):
        try:
            owned_run = history.get_claw_run(owner, state["run_id"])
            if inspect.isawaitable(owned_run):
                owned_run = await owned_run
            if (isinstance(owned_run, dict)
                    and owned_run.get("run_id") == state["run_id"]
                    and owned_run.get("workspace_id") == workspace
                    and isinstance(owned_run.get("conversation_id"), str)
                    and re.fullmatch(
                        r"chat_[a-f0-9]{32}", owned_run["conversation_id"])):
                owned = history.verify_owner_conversation_artifacts(
                    owner, owned_run["conversation_id"],
                )
                if inspect.isawaitable(owned):
                    owned = await owned
                if owned is True:
                    work_conversation = {
                        "conversation_id": owned_run["conversation_id"],
                    }
        except Exception:
            # A missing/stale conversation handle is never fabricated; the
            # workcopy receipt above stays independently available.
            work_conversation = None
    return JSONResponse({
        "ok": True,
        "contract_version": "claw-web-xlsx-p01-status.v1",
        "selection_ref": state["selection_ref"],
        "document_id": state["document_id"],
        "source_sha256": state["source_sha256"],
        "filename": state["filename"],
        "size_bytes": state["size_bytes"],
        "status": state["status"],
        "owner_decision_enabled": ready,
        "owner_request_enabled": request_ready,
        "processing_started": copy is not None,
        "workcopy_created": copy is not None,
        "workcopy_document_id": copy["workcopy_document_id"] if copy else None,
        "work_conversation": work_conversation,
    }, headers=_NO_STORE)

async def web_xlsx_p01_workcopy_download(request: Request) -> Response:
    """Download exactly the approved owner's original-byte workcopy, not a
    generic R2 object, edited workbook, PDF or proof of edit authorization.
    """
    scope = await _scope(request)
    if isinstance(scope, Response):
        return scope
    store, selections, owner, workspace = scope
    ledger = getattr(request.app.state, "web_xlsx_p01_owner_decision_store", None)
    if (not callable(getattr(ledger, "load_status", None))
            or not callable(getattr(store, "find_approved_web_xlsx_workcopy", None))
            or not callable(getattr(store, "get_for_tenant", None))):
        return _error(503, "approved_workcopy_download_unavailable")
    selection_ref = request.path_params.get("selection_ref")
    if not isinstance(selection_ref, str) or not re.fullmatch(
        r"sel_[a-f0-9]{32}", selection_ref
    ):
        return _error(404, "owner_approved_workcopy_not_found")
    try:
        state = await ledger.load_status(
            owner_id=owner, workspace_id=workspace,
            selection_ref=selection_ref,
        )
        if (not isinstance(state, dict) or state.get("status") != "confirmed"
                or not isinstance(state.get("run_id"), str)
                or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._:@+-]{0,127}", state["run_id"])
                or not isinstance(state.get("source_sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", state["source_sha256"])):
            return _error(404, "owner_approved_workcopy_not_found")
        selected = selections.load_owner(
            owner_id=owner, workspace_id=workspace,
            selection_ref=selection_ref,
        )
        if inspect.isawaitable(selected):
            selected = await selected
        original = await store.get_web_xlsx_metadata(
            tenant_id=workspace, owner_id=owner, workspace_id=workspace,
            document_id=state["document_id"],
        )
        if (not isinstance(selected, dict) or not isinstance(original, dict)
                or selected.get("document_id") != state["document_id"]
                or selected.get("source_sha256") != state["source_sha256"]
                or original.get("source_sha256") != state["source_sha256"]
                or original.get("filename") != state["filename"]
                or original.get("size_bytes") != state["size_bytes"]
                or original.get("original_immutable") is not True):
            return _error(404, "owner_approved_workcopy_not_found")
        receipt = await store.find_approved_web_xlsx_workcopy(
            tenant_id=workspace, owner_id=owner, workspace_id=workspace,
            run_id=state["run_id"], source_document_id=state["document_id"],
            expected_source_sha256=state["source_sha256"],
        )
        if not isinstance(receipt, dict) or receipt.get("workcopy_created") is not True:
            return _error(404, "owner_approved_workcopy_not_found")
        document_id = receipt["workcopy_document_id"]
        data = await store.get_for_tenant(
            tenant_id=workspace, document_id=document_id,
        )
        if data is None:
            return _error(404, "owner_approved_workcopy_not_found")
        metadata, payload = data
        from .workspace_storage import XLSX_MEDIA_TYPE
        if (metadata.document_id != document_id
                or metadata.media_type != XLSX_MEDIA_TYPE
                or not isinstance(payload, bytes)
                or hashlib.sha256(payload).hexdigest() != state["source_sha256"]):
            return _error(503, "approved_workcopy_integrity_failed")
    except (KeyError, TypeError, ValueError, AttributeError):
        return _error(503, "approved_workcopy_metadata_invalid")
    except Exception:
        return _error(503, "approved_workcopy_read_unavailable")
    return Response(
        payload, media_type=XLSX_MEDIA_TYPE,
        headers={
            **_NO_STORE,
            "Cross-Origin-Resource-Policy": "same-origin",
            "Vary": "Cookie",
            "Content-Disposition": "attachment; filename*=UTF-8''"
            + quote(original["filename"], safe=""),
            "Content-Length": str(len(payload)),
        },
    )
