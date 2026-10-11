"""#3933 Hark WEB-FIRST write-gated XLSX quote revision routes.

A signed-in browser cannot create a WRITE grant. It may submit only the exact
previewed edit and explicit confirmation. D1 is reserved BEFORE invoking a
trusted, separately configured Engine P01 WRITE client. Default OFF.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .bounded_request_body import read_bounded_request_body, RequestBodyTooLarge
from .claw_web_xlsx_p01_owner_decision_routes import web_xlsx_p01_workcopy_download
from .claw_web_xlsx_p01_request import _utc
from .claw_web_xlsx_selection_routes import _scope
from .claw_web_xlsx_source_routes import _error, _NO_STORE
from .claw_web_xlsx_quote_editor import revise_single_sheet_quote, WebQuoteEditUnsupported
from .claw_web_xlsx_quote_write_store import D1WebQuoteWriteReceiptStore
from .workspace_storage import XLSX_MEDIA_TYPE

WRITE_PATH = "/api/claw/office/web-selections/{selection_ref}/quote-edit/commit"
WRITE_STATUS_PATH = "/api/claw/office/web-selections/{selection_ref}/quote-edit/status"
WRITE_DOWNLOAD_PATH = "/api/claw/office/web-selections/{selection_ref}/quote-edit/download"
_SEL = re.compile(r"sel_[0-9a-f]{32}")
_SHA = re.compile(r"[0-9a-f]{64}")
_DOC = re.compile(r"doc_[0-9a-f]{32}")


def _digest(school_name: str, supply_amount: int) -> str:
    encoded = json.dumps({
        "school_name": school_name, "supply_amount": supply_amount,
        "output_formats": ["xlsx"], "overwrite_original": False,
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


async def _wait(result):
    return await result if inspect.isawaitable(result) else result


async def _owner_context(request: Request):
    scope = await _scope(request)
    if isinstance(scope, Response):
        return scope
    store, _selections, owner, workspace = scope
    receipts = getattr(request.app.state, "web_xlsx_quote_write_store", None)
    original_grants = getattr(request.app.state, "web_xlsx_p01_owner_decision_store", None)
    if not isinstance(receipts, D1WebQuoteWriteReceiptStore):
        return _error(503, "web_xlsx_write_ledger_unavailable")
    if not callable(getattr(original_grants, "load_status", None)):
        return _error(503, "web_xlsx_original_read_authority_unavailable")
    ref = request.path_params.get("selection_ref")
    if type(ref) is not str or not _SEL.fullmatch(ref):
        return _error(404, "web_xlsx_write_selection_not_found")
    try:
        state = await original_grants.load_status(
            owner_id=owner, workspace_id=workspace, selection_ref=ref,
        )
    except Exception:
        return _error(503, "web_xlsx_read_receipt_unavailable")
    if (type(state) is not dict or state.get("status") != "confirmed"
            or not isinstance(state.get("run_id"), str)
            or not _SHA.fullmatch(state.get("source_sha256", ""))):
        return _error(404, "web_xlsx_read_receipt_not_confirmed")
    return store, receipts, owner, workspace, ref, state


def _matches(response: object, row: dict) -> bool:
    # A Core tool completion with exact independent WRITE scope is the
    # necessary authenticated *internal* receipt. Never a browser argument.
    return (type(response) is dict and set(response) == {
        "ok", "core_tool_completed", "operation", "owner_id", "workspace_id",
        "run_id", "source_document_id", "source_sha256", "workcopy_document_id",
        "workcopy_sha256", "edit_sha256", "pdf_exported",
    } and response.get("ok") is True
        and response.get("core_tool_completed") is True
        and response.get("pdf_exported") is False
        and response.get("operation") == "xlsx.quote.revise_workcopy"
        and all(response.get(field) == row[field] for field in (
            "owner_id", "workspace_id", "run_id", "source_document_id",
            "source_sha256", "workcopy_document_id", "edit_sha256",
        )) and response.get("workcopy_sha256") == row["source_sha256"])


async def web_xlsx_quote_edit_commit(request: Request) -> Response:
    context = await _owner_context(request)
    if isinstance(context, Response):
        return context
    store, ledger, owner, workspace, ref, state = context
    client = getattr(request.app.state, "web_xlsx_quote_write_client", None)
    if (getattr(request.app.state, "web_xlsx_quote_write_enabled", False) is not True
            or not callable(getattr(client, "confirm_exact_write", None))
            or not callable(getattr(store, "create_authorized_web_quote_revision", None))):
        return _error(503, "independent_engine_write_p01_unavailable")
    # An old confirmation is not authority to mutate a finished/foreign run.
    history = getattr(request.app.state, "history_store", None)
    if not callable(getattr(history, "get_claw_run", None)):
        return _error(503, "web_xlsx_write_run_authority_unavailable")
    try:
        run = await _wait(history.get_claw_run(owner, state["run_id"]))
        now = datetime.now(timezone.utc)
        if (not isinstance(run, dict) or run.get("run_id") != state["run_id"]
                or run.get("workspace_id") != workspace
                or run.get("status") != "running"
                or not isinstance(run.get("conversation_id"), str)
                or not run["conversation_id"]
                or _utc(run["updated_at"]) > now
                or _utc(run["updated_at"]) + timedelta(minutes=30) <= now):
            return _error(404, "web_xlsx_write_run_not_active")
    except Exception:
        return _error(503, "web_xlsx_write_run_authority_unavailable")
    if request.headers.get("content-type", "").split(";", 1)[0].lower().strip() != "application/json":
        return _error(415, "unsupported_media_type")
    try:
        raw = await read_bounded_request_body(request, max_bytes=512)
    except RequestBodyTooLarge:
        return _error(413, "web_xlsx_write_request_too_large")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return _error(400, "invalid_web_xlsx_write_json")
    if (type(data) is not dict
            or set(data) != {"school_name", "supply_amount", "edit_sha256"}
            or type(data["school_name"]) is not str
            or type(data["supply_amount"]) is not int
            or type(data["edit_sha256"]) is not str
            or not _SHA.fullmatch(data["edit_sha256"])
            or data["edit_sha256"] != _digest(data["school_name"], data["supply_amount"])):
        return _error(400, "web_xlsx_write_edit_digest_invalid")

    # Reapply the exact owner+read-approval+R2/sha boundary as download. No
    # copy-by-ID from the browser; check the actual bytes BEFORE D1 reservation.
    verified = await web_xlsx_p01_workcopy_download(request)
    if verified.status_code != 200:
        return verified
    payload = verified.body
    if type(payload) is not bytes:
        return _error(503, "web_xlsx_write_original_bytes_invalid")
    try:
        parsed = revise_single_sheet_quote(
            original=payload, original_sha256=state["source_sha256"],
            school_name=data["school_name"], supply_amount=data["supply_amount"],
        )
    except WebQuoteEditUnsupported:
        return _error(422, "web_xlsx_write_unsupported_quote")
    try:
        copy = await store.find_approved_web_xlsx_workcopy(
            tenant_id=workspace, owner_id=owner, workspace_id=workspace,
            run_id=state["run_id"], source_document_id=state["document_id"],
            expected_source_sha256=state["source_sha256"],
        )
    except Exception:
        return _error(503, "web_xlsx_write_workcopy_unavailable")
    if not isinstance(copy, dict) or copy.get("workcopy_created") is not True:
        return _error(404, "web_xlsx_write_workcopy_not_found")
    row = {
        "selection_ref": ref, "owner_id": owner, "user_id": owner,
        "workspace_id": workspace, "run_id": state["run_id"],
        "source_document_id": state["document_id"],
        "source_sha256": state["source_sha256"],
        "workcopy_document_id": copy["workcopy_document_id"],
        "edit_sha256": data["edit_sha256"],
        "school_name": data["school_name"], "supply_amount": data["supply_amount"],
    }
    # Preserve one-shot on any unknown network or storage outcome.
    try:
        await ledger.reserve(row)
    except Exception:
        return _error(409, "web_xlsx_edit_already_reserved_or_ledger_unavailable")
    try:
        proof = await _wait(client.confirm_exact_write(row))
        if not _matches(proof, row):
            return _error(409, "independent_engine_write_p01_not_verified")
        async def exact_grant(**auth):
            return (
                set(auth) == {
                    "owner_id", "workspace_id", "run_id", "source_document_id",
                    "source_sha256", "workcopy_document_id", "workcopy_sha256",
                    "edit_sha256", "operation",
                }
                and all(auth.get(k) == row[k] for k in (
                    "owner_id", "workspace_id", "run_id", "source_document_id",
                    "source_sha256", "workcopy_document_id", "edit_sha256",
                ))
                and auth.get("workcopy_sha256") == row["source_sha256"]
                and auth.get("operation") == "xlsx.quote.revise_workcopy"
                and _matches(proof, row)
            )
        revision = await store.create_authorized_web_quote_revision(
            tenant_id=workspace, owner_id=owner, workspace_id=workspace,
            run_id=row["run_id"], source_document_id=row["source_document_id"],
            expected_source_sha256=row["source_sha256"],
            workcopy_document_id=row["workcopy_document_id"],
            school_name=row["school_name"], supply_amount=row["supply_amount"],
            write_grant_verifier=exact_grant,
        )
        if (revision.get("revision_sha256") != parsed.revised_sha256
                or revision.get("edit_sha256") != row["edit_sha256"]
                or await ledger.commit(row, revision) is not True):
            return _error(503, "web_xlsx_write_completion_unknown")
    except Exception:
        return _error(503, "web_xlsx_write_completion_unknown")
    return JSONResponse({
        "ok": True, "contract_version": "claw-web-xlsx-quote-write.v1",
        "selection_ref": ref, "state": "confirmed",
        "revision_document_id": revision["revision_document_id"],
        "revision_sha256": revision["revision_sha256"],
        "edit_sha256": row["edit_sha256"],
        "revised_xlsx_created": True, "pdf_exported": False,
        "original_overwritten": False,
    }, status_code=201, headers=_NO_STORE)


async def _confirmed(request: Request):
    context = await _owner_context(request)
    if isinstance(context, Response):
        return context
    store, ledger, owner, workspace, ref, state = context
    try:
        receipt = await ledger.load_owner(
            owner_id=owner, workspace_id=workspace, selection_ref=ref,
        )
    except Exception:
        return _error(503, "web_xlsx_write_receipt_unavailable")
    if receipt is None or any(receipt.get(k) != value for k, value in (
        ("run_id", state["run_id"]),
        ("source_document_id", state["document_id"]),
        ("source_sha256", state["source_sha256"]),
        ("user_id", owner), ("workspace_id", workspace),
    )):
        return _error(404, "owner_web_xlsx_revision_not_found")
    return store, receipt, owner, workspace, ref


async def web_xlsx_quote_edit_status(request: Request) -> Response:
    context = await _confirmed(request)
    if isinstance(context, Response):
        return context
    _store, row, _owner, _workspace, ref = context
    confirmed = row["state"] == "confirmed"
    return JSONResponse({
        "ok": True, "contract_version": "claw-web-xlsx-quote-write-status.v1",
        "selection_ref": ref,
        "state": "confirmed" if confirmed else "unknown",
        "revised_xlsx_created": confirmed,
        "revision_document_id": row["revision_document_id"] if confirmed else None,
        "revision_sha256": row["revision_sha256"] if confirmed else None,
        "pdf_exported": False,
        "pdf_download_available": (
            request.app.state.web_xlsx_quote_pdf_enabled is True
            and row["state"] == "confirmed"
        ),
    }, headers=_NO_STORE)


async def web_xlsx_quote_edit_download(request: Request) -> Response:
    context = await _confirmed(request)
    if isinstance(context, Response):
        return context
    store, receipt, owner, workspace, _ref = context
    if (receipt["state"] != "confirmed"
            or type(receipt["revision_document_id"]) is not str
            or not _DOC.fullmatch(receipt["revision_document_id"])
            or type(receipt["revision_sha256"]) is not str
            or not _SHA.fullmatch(receipt["revision_sha256"])):
        return _error(404, "owner_web_xlsx_revision_not_ready")
    try:
        data = await store.get_for_tenant(
            tenant_id=workspace, document_id=receipt["revision_document_id"],
        )
        if data is None:
            return _error(404, "owner_web_xlsx_revision_expired")
        metadata, blob = data
        prefix = (
            f"workspaces/{workspace}/claw/web-office-revisions/"
            f"{owner}/{workspace}/{receipt['run_id']}/"
            f"{receipt['source_document_id']}/{receipt['workcopy_document_id']}/"
            f"{receipt['revision_document_id']}/"
        )
        if (metadata.document_id != receipt["revision_document_id"]
                or metadata.object_key != prefix + receipt["revision_sha256"]
                or metadata.media_type != XLSX_MEDIA_TYPE
                or type(blob) is not bytes
                or hashlib.sha256(blob).hexdigest() != receipt["revision_sha256"]):
            return _error(503, "owner_web_xlsx_revision_integrity_failed")
    except Exception:
        return _error(503, "owner_web_xlsx_revision_read_unavailable")
    return Response(blob, media_type=XLSX_MEDIA_TYPE, headers={
        **_NO_STORE, "Cross-Origin-Resource-Policy": "same-origin",
        "Vary": "Cookie",
        "Content-Disposition": "attachment; filename*=UTF-8''"
        + quote("hark-revised-quote.xlsx", safe=""),
    })
