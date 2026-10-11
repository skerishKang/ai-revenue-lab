"""#3933 signed-in Hark two-phase WRITE: request Core pause, then decide.

The browser does not send a pause, continuation, tool, or grant. Separate
Core WRITE approval MUST complete against B62 D1 033 before storing XLSX.
"""
from __future__ import annotations

import inspect
import json
from datetime import datetime,timedelta,timezone
from starlette.requests import Request
from starlette.responses import JSONResponse,Response

from kagent.p01_approval_continuation import build_first_party_decision_submission
from .bounded_request_body import read_bounded_request_body,RequestBodyTooLarge
from .claw_web_xlsx_quote_write_routes import (
    _owner_context,_matches,_digest,_wait,_NO_STORE,_error,
    web_xlsx_p01_workcopy_download,
)
from .claw_web_xlsx_quote_editor import revise_single_sheet_quote,WebQuoteEditUnsupported
from .claw_web_xlsx_quote_write_pause_store import D1WebQuoteWritePauseStore
from .claw_web_xlsx_quote_write_owner_decision import D1WebQuoteWriteOwnerDecisionStore
from .claw_web_xlsx_p01_request import _utc

REQUEST="/api/claw/office/web-selections/{selection_ref}/quote-edit/request"
DECISION="/api/claw/office/web-selections/{selection_ref}/quote-edit/decision"
DECISION_STATUS="/api/claw/office/web-selections/{selection_ref}/quote-edit/approval-status"


async def _scope(request):
    context=await _owner_context(request)
    if isinstance(context,Response):
        return context
    store,ledger,owner,workspace,ref,read=context
    pause_store=getattr(request.app.state,"web_xlsx_quote_write_pause_store",None)
    owner_store=getattr(request.app.state,"web_xlsx_quote_write_owner_decision_store",None)
    client=getattr(request.app.state,"web_xlsx_quote_write_client",None)
    if (getattr(request.app.state,"web_xlsx_quote_write_enabled",False) is not True
            or not isinstance(pause_store,D1WebQuoteWritePauseStore)
            or not isinstance(owner_store,D1WebQuoteWriteOwnerDecisionStore)
            or not callable(getattr(client,"start_pause",None))
            or not callable(getattr(client,"resume_owner_decision",None))):
        return _error(503,"independent_engine_write_p01_unavailable")
    history=getattr(request.app.state,"history_store",None)
    if not callable(getattr(history,"get_claw_run",None)):
        return _error(503,"write_run_unavailable")
    try:
        run=await _wait(history.get_claw_run(owner,read["run_id"]))
        now=datetime.now(timezone.utc)
        if (type(run) is not dict or run.get("run_id")!=read["run_id"]
                or run.get("workspace_id")!=workspace
                or run.get("status")!="running"
                or not run.get("conversation_id")
                or not _utc(run["updated_at"])<=now
                or not _utc(run["updated_at"])+timedelta(minutes=30)>now):
            return _error(404,"owner_write_run_not_active")
    except Exception:
        return _error(503,"owner_write_run_unavailable")
    return store,ledger,owner,workspace,ref,read,pause_store,owner_store,client


async def _json(request,max_size,fields):
    if request.headers.get("content-type","").split(";",1)[0].lower().strip()!="application/json":
        return _error(415,"unsupported_media_type")
    try:
        raw=await read_bounded_request_body(request,max_bytes=max_size)
        value=json.loads(raw.decode("utf-8"))
    except RequestBodyTooLarge:
        return _error(413,"write_request_too_large")
    except (ValueError,UnicodeDecodeError):
        return _error(400,"write_json_invalid")
    if type(value) is not dict or set(value)!=fields:
        return _error(400,"write_request_fields_invalid")
    return value


async def request_quote_write(request:Request)->Response:
    scope=await _scope(request)
    if isinstance(scope,Response): return scope
    store,ledger,owner,workspace,ref,read,pause_store,_owner_store,client=scope
    data=await _json(request,512,{"school_name","supply_amount","edit_sha256"})
    if isinstance(data,Response): return data
    name=data["school_name"]; amount=data["supply_amount"]; digest=data["edit_sha256"]
    if (type(name) is not str or type(amount) is not int or type(digest) is not str
            or not 1<=len(name)<=120 or not 1<=amount<=999999999999
            or amount%10 or digest!=_digest(name,amount)):
        return _error(400,"invalid_write_edit_digest")

    verified=await web_xlsx_p01_workcopy_download(request)
    if verified.status_code!=200: return verified
    try:
        parsed=revise_single_sheet_quote(
            original=verified.body,original_sha256=read["source_sha256"],
            school_name=name,supply_amount=amount)
    except (WebQuoteEditUnsupported,ValueError,TypeError):
        return _error(422,"unsupported_quote_edit")
    try:
        workcopy=await store.find_approved_web_xlsx_workcopy(
            tenant_id=workspace,owner_id=owner,workspace_id=workspace,
            run_id=read["run_id"],source_document_id=read["document_id"],
            expected_source_sha256=read["source_sha256"])
    except Exception:
        return _error(503,"write_workcopy_unavailable")
    if not isinstance(workcopy,dict) or workcopy.get("workcopy_created") is not True:
        return _error(404,"write_workcopy_not_found")
    row={
        "selection_ref":ref,"owner_id":owner,"user_id":owner,"workspace_id":workspace,
        "run_id":read["run_id"],"source_document_id":read["document_id"],
        "source_sha256":read["source_sha256"],
        "workcopy_document_id":workcopy["workcopy_document_id"],
        "edit_sha256":digest,"school_name":name,"supply_amount":amount,
    }
    # Record both immutable edit and the dispatch attempt *before*
    # making an external Engine call. All unknown outcomes are terminal.
    try:
        await ledger.reserve(row)
        await pause_store.reserve(row)
    except Exception:
        return _error(409,"write_request_already_reserved_or_unavailable")
    try:
        emitted=await _wait(client.start_pause(row))
        if (type(emitted) is not dict or set(emitted)!={
                "pause_id","continuation_ref","expires_at","status"}
                or emitted["status"]!="paused"
                or not await pause_store.commit(
                    row,pause_id=emitted["pause_id"],
                    continuation_ref=emitted["continuation_ref"],
                    expires_at=emitted["expires_at"])):
            return _error(503,"engine_write_pause_unknown")
    except Exception:
        return _error(503,"engine_write_pause_unknown")
    return JSONResponse({
        "ok":True,"contract_version":"claw-web-xlsx-quote-write-pause.v1",
        "selection_ref":ref,"state":"waiting_p01",
        "edit_sha256":digest,"school_name":name,"supply_amount":amount,
        "write_approved":False,"revised_xlsx_created":False,"pdf_exported":False,
        "original_overwritten":False,
    },status_code=202,headers=_NO_STORE)


async def decide_quote_write(request:Request)->Response:
    scope=await _scope(request)
    if isinstance(scope,Response): return scope
    store,ledger,owner,workspace,ref,read,pause_store,owner_store,client=scope
    data=await _json(request,128,{"decision"})
    if isinstance(data,Response): return data
    outcome=data["decision"]
    if type(outcome) is not str or outcome not in ("approve","deny"):
        return _error(400,"invalid_write_decision")
    paused=await pause_store.load_owner(owner_id=owner,workspace_id=workspace,selection_ref=ref)
    reserved=await owner_store.load_waiting(owner_id=owner,workspace_id=workspace,selection_ref=ref)
    if (not paused or paused.get("status")!="waiting_p01" or not reserved
            or any(paused.get(k)!=reserved.get(k) for k in (
                "selection_ref","user_id","workspace_id","run_id",
                "source_document_id","source_sha256","workcopy_document_id","edit_sha256"))
            or read["source_sha256"]!=reserved["source_sha256"]
            or read["document_id"]!=reserved["source_document_id"]
            or read["run_id"]!=reserved["run_id"]
            or _utc(paused["pause_expires_at"])<=datetime.now(timezone.utc)):
        return _error(404,"owner_write_pause_not_found")
    row={**reserved,"owner_id":owner}
    try:
        submission=build_first_party_decision_submission(
            pause_id=paused["pause_id"],decision=outcome,owner_id=owner)
        await owner_store.reserve(
            row=row,pause_id=paused["pause_id"],
            continuation_ref=paused["continuation_ref"],outcome=outcome)
    except Exception:
        return _error(409,"owner_write_decision_already_consumed")
    try:
        result=await _wait(client.resume_owner_decision(
            continuation_ref=paused["continuation_ref"],submission=submission))
        if type(result) is not dict or result.get("ok") is not True:
            return _error(503,"engine_write_decision_unknown")
        if outcome=="deny":
            if result.get("status")!="denied":
                return _error(503,"engine_write_decision_unknown")
            if await owner_store.finish(
                    row=row,pause_id=paused["pause_id"],
                    continuation_ref=paused["continuation_ref"],
                    outcome=outcome,engine_status="denied") is not True:
                return _error(503,"engine_write_decision_unknown")
            return JSONResponse({
                "ok":True,"contract_version":"claw-web-xlsx-quote-write-decision.v1",
                "selection_ref":ref,"state":"denied","revised_xlsx_created":False,
                "pdf_exported":False,
            },headers=_NO_STORE)
        proof=result.get("proof")
        if result.get("status")!="confirmed" or not _matches(proof,row):
            return _error(503,"engine_write_decision_unknown")
        # Verify the private source and its exact bytes again AFTER Core resume.
        fresh=await web_xlsx_p01_workcopy_download(request)
        if fresh.status_code!=200:return _error(503,"approved_write_source_changed")
        parsed=revise_single_sheet_quote(
            original=fresh.body,original_sha256=row["source_sha256"],
            school_name=row["school_name"],supply_amount=row["supply_amount"])
        async def exact_grant(**auth):
            return (set(auth)=={
                "owner_id","workspace_id","run_id","source_document_id",
                "source_sha256","workcopy_document_id","workcopy_sha256",
                "edit_sha256","operation",
            } and all(auth.get(k)==row[k] for k in (
                "owner_id","workspace_id","run_id","source_document_id",
                "source_sha256","workcopy_document_id","edit_sha256"))
                and auth.get("workcopy_sha256")==row["source_sha256"]
                and auth.get("operation")=="xlsx.quote.revise_workcopy"
                and _matches(proof,row))
        revision=await store.create_authorized_web_quote_revision(
            tenant_id=workspace,owner_id=owner,workspace_id=workspace,
            run_id=row["run_id"],source_document_id=row["source_document_id"],
            expected_source_sha256=row["source_sha256"],
            workcopy_document_id=row["workcopy_document_id"],
            school_name=row["school_name"],supply_amount=row["supply_amount"],
            write_grant_verifier=exact_grant)
        if (revision.get("revision_sha256")!=parsed.revised_sha256
                or revision.get("edit_sha256")!=row["edit_sha256"]
                or await ledger.commit(row,revision) is not True
                or await owner_store.finish(
                    row=row,pause_id=paused["pause_id"],
                    continuation_ref=paused["continuation_ref"],outcome=outcome,
                    engine_status="confirmed") is not True):
            return _error(503,"engine_write_completion_unknown")
    except Exception:
        return _error(503,"engine_write_completion_unknown")
    return JSONResponse({
        "ok":True,"contract_version":"claw-web-xlsx-quote-write.v1",
        "selection_ref":ref,"state":"confirmed",
        "revision_document_id":revision["revision_document_id"],
        "revision_sha256":revision["revision_sha256"],
        "edit_sha256":row["edit_sha256"],
        "revised_xlsx_created":True,"pdf_exported":False,
        "original_overwritten":False,
    },status_code=201,headers=_NO_STORE)


async def quote_write_approval_status(request:Request)->Response:
    context=await _owner_context(request)
    if isinstance(context,Response):return context
    _store,ledger,owner,workspace,ref,_read=context
    pause_store=getattr(request.app.state,"web_xlsx_quote_write_pause_store",None)
    owner_store=getattr(request.app.state,"web_xlsx_quote_write_owner_decision_store",None)
    if not isinstance(pause_store,D1WebQuoteWritePauseStore) or not isinstance(owner_store,D1WebQuoteWriteOwnerDecisionStore):
        return _error(503,"write_approval_ledger_unavailable")
    paused=await pause_store.load_owner(owner_id=owner,workspace_id=workspace,selection_ref=ref)
    if paused is None:return _error(404,"owner_write_pause_not_found")
    receipt=await ledger.load_owner(owner_id=owner,workspace_id=workspace,selection_ref=ref)
    item=await _wait(owner_store.db.prepare(
        "SELECT state FROM claw_web_xlsx_quote_write_decisions WHERE "
        "selection_ref=? AND user_id=? AND workspace_id=? LIMIT 1"
    ).bind(ref,owner,workspace).first())
    from .workspace_storage import _row_to_dict
    d=_row_to_dict(item)
    state=("confirmed" if receipt and receipt["state"]=="confirmed" and d and d["state"]=="confirmed"
           else "denied" if d and d["state"]=="denied"
           else "unknown" if d and d["state"]=="dispatching"
           else "waiting_p01" if paused["status"]=="waiting_p01"
               and _utc(paused["pause_expires_at"])>datetime.now(timezone.utc)
           else "unknown")
    return JSONResponse({
        "ok":True,"contract_version":"claw-web-xlsx-quote-write-approval-status.v1",
        "selection_ref":ref,"state":state,
        "write_approved":state=="confirmed",
        "edit_sha256":receipt["edit_sha256"] if receipt else None,
        "school_name":receipt["school_name"] if receipt else None,
        "supply_amount":receipt["supply_amount"] if receipt else None,
        "revised_xlsx_created":state=="confirmed",
        "pdf_exported":False,
    },headers=_NO_STORE)
