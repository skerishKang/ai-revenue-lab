"""#3933 actual Hark POST write request -> owner consent -> XLSX delivery.

Mock trusted Engine boundary; verifies genuine B62 browser routes + R2/D1.
Does not claim Production Engine Service Binding is enabled.
"""
from __future__ import annotations
import sys
from datetime import datetime,timedelta,timezone
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).parent))
from test_3933_web_quote_write_gate import prepared,VALUES,api,OWNER,FOREIGN
from test_3580_web_xlsx_selection_routes import RealSQLiteD1
from app.claw_web_xlsx_quote_write_pause_store import D1WebQuoteWritePauseStore
from app.claw_web_xlsx_quote_write_owner_decision import D1WebQuoteWriteOwnerDecisionStore

P="pause:"+"b"*32
C="cont_"+"c"*32

class PrivateCoreWrite:
    def __init__(self,db,mode="approved"):
        self.db,self.mode=db,mode
        self.started=[];self.resumed=[];self.row=None

    async def start_pause(self,row):
        self.started.append(dict(row));self.row=dict(row)
        assert self.db.execute(
            "SELECT status FROM claw_web_xlsx_quote_write_pauses"
        ).fetchone()["status"]=="dispatching"
        if self.mode=="start_unknown":raise RuntimeError("Engine no response")
        return {
            "status":"paused","pause_id":P,"continuation_ref":C,
            "expires_at":(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat(),
        }

    async def resume_owner_decision(self,*,continuation_ref,submission):
        self.resumed.append((continuation_ref,dict(submission)))
        assert continuation_ref==C
        d=self.db.execute(
            "SELECT pause_id,continuation_ref,outcome,state,edit_sha256 "
            "FROM claw_web_xlsx_quote_write_decisions",
        ).fetchone()
        assert d and d["state"]=="dispatching"
        assert d["pause_id"]==P and d["continuation_ref"]==C
        assert d["edit_sha256"]==self.row["edit_sha256"]
        if self.mode=="resume_unknown":raise RuntimeError("Engine outcome unknown")
        if self.mode=="spoof":status="confirmed"
        else:status="denied" if d["outcome"]=="deny" else "confirmed"
        proof={
            "ok":True,"core_tool_completed":True,
            "operation":"xlsx.quote.revise_workcopy",
            "owner_id":self.row["owner_id"],
            "workspace_id":self.row["workspace_id"],"run_id":self.row["run_id"],
            "source_document_id":self.row["source_document_id"],
            "source_sha256":self.row["source_sha256"],
            "workcopy_document_id":self.row["workcopy_document_id"],
            "workcopy_sha256":self.row["source_sha256"],
            "edit_sha256":self.row["edit_sha256"],"pdf_exported":False,
        }
        if self.mode=="spoof":proof["edit_sha256"]="f"*64
        return {"ok":True,"status":status,"proof":proof} if status=="confirmed" else {
            "ok":True,"status":"denied"}

async def setup(monkeypatch,mode="approved"):
    app,settings,meta,r2,db,history,sel,src,initial,preview=await prepared(
        monkeypatch,enabled=False)
    directory=Path(__file__).resolve().parents[1]/"migrations"
    for n in ("033_claw_web_xlsx_quote_write_decisions.sql",
              "034_claw_web_xlsx_quote_write_pauses.sql"):
        db.executescript((directory/n).read_text(encoding="utf-8"))
    app.state.web_xlsx_quote_write_pause_store=D1WebQuoteWritePauseStore(RealSQLiteD1(db))
    app.state.web_xlsx_quote_write_owner_decision_store=D1WebQuoteWriteOwnerDecisionStore(RealSQLiteD1(db))
    client=PrivateCoreWrite(db,mode)
    app.state.web_xlsx_quote_write_client=client
    app.state.web_xlsx_quote_write_enabled=True
    return app,settings,meta,r2,db,history,sel,src,initial,preview,client


@pytest.mark.asyncio
async def test_explicit_owner_approve_after_genuine_separate_core_pause(monkeypatch):
    app,settings,meta,r2,db,history,sel,src,before,preview,client=await setup(monkeypatch)
    ref=sel["selection_ref"]
    payload={**VALUES,"edit_sha256":preview["edit_sha256"]}
    request=await api(app,settings,ref,"request",method="POST",data=payload)
    assert request.status_code==202,request.text
    assert request.json()["state"]=="waiting_p01"
    assert request.json()["write_approved"] is False
    assert len(r2.objects)==len(before)
    assert len(client.started)==1
    assert (await api(app,settings,ref,"request",method="POST",data=payload)).status_code==409
    assert (await api(app,settings,ref,"decision",method="POST",
                      data={"decision":"approve"},owner=FOREIGN)).status_code==404
    assert (await api(app,settings,ref,"approval-status")).json()["state"]=="waiting_p01"
    approved=await api(app,settings,ref,"decision",method="POST",data={"decision":"approve"})
    assert approved.status_code==201,approved.text
    assert approved.json()["revised_xlsx_created"] is True
    assert approved.json()["revision_sha256"]==preview["revision_preview_sha256"]
    assert (await api(app,settings,ref,"approval-status")).json()["state"]=="confirmed"
    dl=await api(app,settings,ref,"download")
    assert dl.status_code==200
    assert len(r2.objects)==len(before)+1
    assert all(r2.objects[k]==v for k,v in before.items())
    assert len(client.resumed)==1
    assert client.resumed[0][1]["pause_id"]==P
    assert (await api(app,settings,ref,"decision",method="POST",
                      data={"decision":"approve"})).status_code in (404,409)
    assert len(client.resumed)==1
    db.close()


@pytest.mark.asyncio
async def test_explicit_owner_denial_consumes_without_revision(monkeypatch):
    app,settings,meta,r2,db,history,sel,src,before,preview,client=await setup(monkeypatch)
    ref=sel["selection_ref"]
    p={**VALUES,"edit_sha256":preview["edit_sha256"]}
    assert (await api(app,settings,ref,"request",method="POST",data=p)).status_code==202
    denied=await api(app,settings,ref,"decision",method="POST",data={"decision":"deny"})
    assert denied.status_code==200,denied.text
    assert denied.json()["revised_xlsx_created"] is False
    assert (await api(app,settings,ref,"approval-status")).json()["state"]=="denied"
    assert (await api(app,settings,ref,"download")).status_code==404
    assert r2.objects==before
    db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode",["start_unknown","resume_unknown","spoof"])
async def test_no_retry_or_write_for_unknown_or_forged_engine_result(monkeypatch,mode):
    app,settings,meta,r2,db,history,sel,src,before,preview,client=await setup(monkeypatch,mode)
    ref=sel["selection_ref"]
    p={**VALUES,"edit_sha256":preview["edit_sha256"]}
    first=await api(app,settings,ref,"request",method="POST",data=p)
    if mode=="start_unknown":
        assert first.status_code==503
        assert (await api(app,settings,ref,"request",method="POST",data=p)).status_code==409
        assert not client.resumed
    else:
        assert first.status_code==202
        second=await api(app,settings,ref,"decision",method="POST",
                         data={"decision":"approve"})
        assert second.status_code==503
        assert (await api(app,settings,ref,"approval-status")).json()["state"]=="unknown"
        assert (await api(app,settings,ref,"decision",method="POST",
                          data={"decision":"approve"})).status_code==409
        assert len(client.resumed)==1
    assert r2.objects==before
    db.close()


@pytest.mark.asyncio
async def test_browser_cannot_include_direct_engine_tool_or_grant(monkeypatch):
    app,settings,meta,r2,db,history,sel,src,before,preview,client=await setup(monkeypatch)
    ref=sel["selection_ref"]
    bad={**VALUES,"edit_sha256":preview["edit_sha256"],"approved":True}
    assert (await api(app,settings,ref,"request",method="POST",data=bad)).status_code==400
    assert (await api(app,settings,ref,"decision",method="POST",
                      data={"decision":"approve","continuation_ref":C})).status_code==400
    assert not client.started and not client.resumed
    assert r2.objects==before
    db.close()
