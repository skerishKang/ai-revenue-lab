"""One-shot, owner-scoped WRITE Core pause recorded BEFORE owner decision."""
from __future__ import annotations
import inspect
import re
from datetime import datetime,timezone
from .claw_web_xlsx_quote_write_store import D1WebQuoteWriteReceiptStore
from .workspace_storage import _row_to_dict

_PAUSE=re.compile(r"pause:[0-9a-f]{24,64}")
_CONT=re.compile(r"cont_[A-Za-z0-9_-]{8,123}")

async def _aw(x):
    return await x if inspect.isawaitable(x) else x

class D1WebQuoteWritePauseStore:
    def __init__(self,db):
        if not callable(getattr(db,"prepare",None)):
            raise ValueError("private B62 D1 required")
        self.db=db
        self.edits=D1WebQuoteWriteReceiptStore(db)

    async def reserve(self,row):
        self.edits.validate(row)
        existing=await self.edits.load_owner(owner_id=row["user_id"],
            workspace_id=row["workspace_id"],selection_ref=row["selection_ref"])
        fields=("selection_ref","user_id","workspace_id","run_id",
            "source_document_id","source_sha256","workcopy_document_id","edit_sha256",
            "school_name","supply_amount")
        if not existing or existing["state"]!="dispatching" or any(
            existing.get(k)!=row.get(k) for k in fields):
            raise ValueError("immutable edit no longer reserved")
        now=datetime.now(timezone.utc).isoformat()
        await _aw(self.db.prepare(
            "INSERT INTO claw_web_xlsx_quote_write_pauses "
            "(selection_ref,user_id,workspace_id,run_id,source_document_id,"
            "source_sha256,workcopy_document_id,edit_sha256,status,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,'dispatching',?,?)"
        ).bind(*(row[k] for k in fields[:8]),now,now).run())

    async def commit(self,row,*,pause_id,continuation_ref,expires_at):
        self.edits.validate(row)
        from .claw_web_xlsx_p01_request import _utc
        now=datetime.now(timezone.utc)
        if (not isinstance(pause_id,str) or not _PAUSE.fullmatch(pause_id)
                or not isinstance(continuation_ref,str) or not _CONT.fullmatch(continuation_ref)
                or not isinstance(expires_at,str) or not now < _utc(expires_at)
                or _utc(expires_at)>now.replace(year=now.year+1)):
            raise ValueError("invalid Core WRITE pause")
        await _aw(self.db.prepare(
            "UPDATE claw_web_xlsx_quote_write_pauses SET "
            "status='waiting_p01',pause_id=?,continuation_ref=?,pause_expires_at=?,"
            "updated_at=? WHERE selection_ref=? AND user_id=? AND workspace_id=? "
            "AND run_id=? AND source_document_id=? AND source_sha256=? "
            "AND workcopy_document_id=? AND edit_sha256=? AND status='dispatching'"
        ).bind(pause_id,continuation_ref,expires_at,now.isoformat(),
            *(row[k] for k in ("selection_ref","user_id","workspace_id","run_id",
               "source_document_id","source_sha256","workcopy_document_id","edit_sha256"))).run())
        final=await self.load_owner(owner_id=row["user_id"],
            workspace_id=row["workspace_id"],selection_ref=row["selection_ref"])
        return bool(final and final["status"]=="waiting_p01"
            and final["pause_id"]==pause_id and final["continuation_ref"]==continuation_ref)

    async def load_owner(self,*,owner_id,workspace_id,selection_ref):
        if type(selection_ref) is not str or not re.fullmatch(r"sel_[0-9a-f]{32}",selection_ref):
            return None
        return _row_to_dict(await _aw(self.db.prepare(
            "SELECT selection_ref,user_id,workspace_id,run_id,source_document_id,"
            "source_sha256,workcopy_document_id,edit_sha256,status,pause_id,"
            "continuation_ref,pause_expires_at FROM claw_web_xlsx_quote_write_pauses "
            "WHERE selection_ref=? AND user_id=? AND workspace_id=? LIMIT 1"
        ).bind(selection_ref,owner_id,workspace_id).first()))
