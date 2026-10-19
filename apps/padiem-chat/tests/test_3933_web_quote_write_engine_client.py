"""Fixed private B62->Engine P01 WRITE transport; no browser bypass."""
from __future__ import annotations
import json
from types import SimpleNamespace
import pytest
from app.web_xlsx_quote_write_engine_client import (
    CloudflareWebQuoteWriteP01Client,
)
from app.claw_web_xlsx_p01_request import WebXlsxP01RequestError

REF="sel_"+"a"*32
PAUSE="pause:"+"b"*32
CONT="cont_"+"c"*36
DOC="doc_"+"d"*32
COPY="doc_"+"e"*32
HASH="f"*64

def row():
    return {
        "selection_ref":REF,"user_id":"owner_web_a","owner_id":"owner_web_a",
        "workspace_id":"owner:web_a","run_id":"run_web_a",
        "source_document_id":DOC,"source_sha256":HASH,
        "workcopy_document_id":COPY,"edit_sha256":"a"*64,
        "school_name":"Gwangju University","supply_amount":99200000,
    }

class Request:
    def __init__(self,url,**kwargs):
        self.url=url;self.kwargs=kwargs;self.js_object=self

class Binding:
    def __init__(self,results):
        self.results=results;self.requests=[]
    async def fetch(self,request):
        self.requests.append(request)
        status,payload=self.results.pop(0)
        async def text():
            return json.dumps(payload)
        return SimpleNamespace(status=status,text=text,body=None)

def client(results):
    binding=Binding(results)
    instance=CloudflareWebQuoteWriteP01Client(
        binding,caller_id="b62_test_caller",
        credential="test_private_engine_token",request_factory=Request,
    )
    return instance,binding

def pause_response():
    return {
        "ok":True,"tool":{
            "canonical_tool_id":"tool:padiem:web-xlsx-quote-write@1",
            "status":"paused","continuation_ref":CONT,
            "approval_pause":{"continuation_id":PAUSE,
                              "expires_at":"2030-01-01T00:00:00+00:00"},
        },
    }
def proof():
    x=row()
    return {
        "ok":True,"core_tool_completed":True,
        "operation":"xlsx.quote.revise_workcopy",
        "owner_id":x["owner_id"],"workspace_id":x["workspace_id"],
        "run_id":x["run_id"],"source_document_id":DOC,
        "source_sha256":HASH,"workcopy_document_id":COPY,
        "workcopy_sha256":HASH,"edit_sha256":x["edit_sha256"],
        "pdf_exported":False,
    }

@pytest.mark.asyncio
async def test_fixed_private_write_core_start_resume_scope():
    submission={
        "decision_id":"decision_b54_"+ "a"*32,
        "pause_id":PAUSE,"outcome":"approved",
        "authority_ref":"b54_session:owner_web_a",
        "evidence_ref":"b54_decision:"+"a"*32,
        "decided_at":"2026-10-11T10:00:00+00:00",
    }
    c,b=client([(202,pause_response()),(200,{
        "ok":True,"tool":{
            "canonical_tool_id":"tool:padiem:web-xlsx-quote-write@1",
            "status":"completed","continuation_ref":CONT,"output":proof(),
        },
    })])
    started=await c.start_pause(row())
    assert started["status"]=="paused"
    assert started["pause_id"]==PAUSE
    assert started["continuation_ref"]==CONT
    ended=await c.resume_owner_decision(
        continuation_ref=CONT,submission=submission,
    )
    assert ended["status"]=="confirmed"
    assert ended["proof"]==proof()
    assert len(b.requests)==2
    first=json.loads(b.requests[0].kwargs["body"])
    assert first["app_id"]=="padiem-web-xlsx-write-p01"
    assert first["arguments"]["edit_sha256"]==row()["edit_sha256"]
    assert first["arguments"]["overwrite_original"] is False
    assert first["arguments"]["drive_write"] is False
    assert first["arguments"]["pdf_exported"] is False
    assert not any(k in first for k in ("user_password","api_key","file_content"))
    assert b.requests[0].url.endswith("/internal/v1/tools/execute")
    assert b.requests[1].url.endswith("/internal/v1/tools/resume")
    resume=json.loads(b.requests[1].kwargs["body"])
    assert set(resume)=={"app_id","continuation_ref","decision"}
    assert set(resume["decision"])==set(submission)

@pytest.mark.asyncio
async def test_core_transport_refuses_forged_pause_and_fake_completion():
    start,b=client([(202,{"ok":True,"tool":{
        "canonical_tool_id":"tool:padiem:web-xlsx-confirm@1",
        "status":"paused","continuation_ref":CONT,
        "approval_pause":{"continuation_id":PAUSE,
                          "expires_at":"2030-01-01T00:00:00+00:00"},
    }})])
    with pytest.raises(WebXlsxP01RequestError):
        await start.start_pause(row())
    assert len(b.requests)==1
    altered={**proof(),"edit_sha256":"b"*64}
    resumed,bind=client([(200,{"ok":True,"tool":{
        "canonical_tool_id":"tool:padiem:web-xlsx-confirm@1",
        "status":"completed","continuation_ref":CONT,"output":altered,
    }})])
    with pytest.raises(WebXlsxP01RequestError):
        await resumed.resume_owner_decision(continuation_ref=CONT,submission={
            "decision_id":"decision_test","pause_id":PAUSE,"outcome":"approved",
            "authority_ref":"trusted","evidence_ref":"trusted",
            "decided_at":"2026-10-11T10:00:00+00:00",
        })
    assert len(bind.requests)==1

@pytest.mark.asyncio
async def test_denial_cannot_mint_write_proof():
    c,b=client([(409,{"ok":False,"error":{"code":"approval_denied"}})])
    result=await c.resume_owner_decision(continuation_ref=CONT,submission={
        "decision_id":"decision_test","pause_id":PAUSE,"outcome":"denied",
        "authority_ref":"first_party","evidence_ref":"first_party",
        "decided_at":"2026-10-11T10:00:00+00:00",
    })
    assert result=={"ok":True,"status":"denied"}
    assert len(b.requests)==1
