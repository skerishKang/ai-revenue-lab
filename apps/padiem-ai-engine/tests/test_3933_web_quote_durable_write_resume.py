"""Durable Core WRITE pause+decision across separate Engine service instances.

No mocked grant: the Engine independently reads a real synthetic B62 D1
original approval + EDIT 032 + owner WRITE 033 and consumes the pause once.
"""
from __future__ import annotations

import hashlib
import sys
from datetime import datetime,timezone
from pathlib import Path
import pytest

sys.path.insert(0,str(Path(__file__).parent))
from test_3933_web_quote_owner_write_grant import prepared as prepared_d1
from test_3933_web_quote_write_core import (
    SEL,OWNER,D1 as B62D1,
)
from test_3580_web_xlsx_durable_tool_pending import (
    database as engine_database,SQLiteD1,
)
from app.approval_verifier import AuthenticatedFirstPartyApprovalDecisionVerifier
from app.tool_execution_service import ToolExecutionEngineService
from app.web_xlsx_quote_write_tool_binding import (
    APP_ID,AGENT_ID,CANONICAL_TOOL,
    build_web_quote_write_tool_binding,quote_write_arguments,
)
from app.web_xlsx_quote_write_scope_d1 import D1WebQuoteWriteScopeResolver
from app.web_xlsx_quote_write_tool_pending_d1 import D1WebQuoteWriteToolPendingStore
from app.web_xlsx_quote_write_owner_approval_d1 import D1WebQuoteOwnerWriteApprovalGrant


def service(b62, engine):
    resolver=D1WebQuoteWriteScopeResolver(B62D1(b62))
    binding=build_web_quote_write_tool_binding(resolver)
    return ToolExecutionEngineService(
        tool_binding_resolver=lambda app:binding if app==APP_ID else None,
        continuation_store=D1WebQuoteWriteToolPendingStore(SQLiteD1(engine)),
        approval_decision_verifier=AuthenticatedFirstPartyApprovalDecisionVerifier(),
        web_quote_write_approval_grant=D1WebQuoteOwnerWriteApprovalGrant(B62D1(b62)),
    )


async def create_pause(outcome="approve"):
    b62,_,_,_=await prepared_d1(outcome)
    engine=engine_database()
    engine.executescript((Path(__file__).resolve().parents[1] / "migrations" / "0010_web_quote_write_tool_continuations.sql").read_text(encoding="utf-8"))
    scope=await D1WebQuoteWriteScopeResolver(B62D1(b62))(SEL)
    response=await service(b62,engine).execute_payload({
        "app_id":APP_ID,"agent_id":AGENT_ID,"tool_id":CANONICAL_TOOL,
        "arguments":quote_write_arguments(scope),
    })
    assert response.status_code==202,response.body
    tool=response.body["tool"]
    assert tool["status"]=="paused"
    paused_id=tool["approval_pause"]["continuation_id"]
    continuation=tool["continuation_ref"]
    b62.execute(
        "UPDATE claw_web_xlsx_quote_write_decisions "
        "SET pause_id=?,continuation_ref=? WHERE selection_ref=?",
        (paused_id,continuation,SEL),
    )
    name="approved" if outcome=="approve" else "denied"
    did="decision_b54_"+hashlib.sha256(
        f"{OWNER}|{paused_id}|{name}".encode()).hexdigest()[:32]
    decision={
        "decision_id":did,"pause_id":paused_id,"outcome":name,
        "authority_ref":"b54_session:"+OWNER,
        "evidence_ref":"b54_decision:"+did,
        "decided_at":datetime.now(timezone.utc).isoformat(),
    }
    return b62,engine,tool,decision


@pytest.mark.asyncio
async def test_real_durable_core_write_approval_survives_engine_recreation():
    b62,engine,tool,decision=await create_pause()
    reply=await service(b62,engine).resume_payload({
        "app_id":APP_ID,"continuation_ref":tool["continuation_ref"],
        "decision":decision,
    })
    assert reply.status_code==200,reply.body
    assert reply.body["tool"]["status"]=="completed"
    result=reply.body["tool"]["output"]
    assert result["core_tool_completed"] is True
    assert result["pdf_exported"] is False
    assert result["operation"]=="xlsx.quote.revise_workcopy"
    assert engine.execute(
        "SELECT state FROM padiem_web_quote_write_tool_continuations"
    ).fetchone()["state"]=="consumed"
    repeated=await service(b62,engine).resume_payload({
        "app_id":APP_ID,"continuation_ref":tool["continuation_ref"],
        "decision":decision,
    })
    assert repeated.status_code==409,repeated.body
    b62.close();engine.close()


@pytest.mark.asyncio
async def test_real_durable_core_write_denial_never_returns_file_grant():
    b62,engine,tool,decision=await create_pause("deny")
    reply=await service(b62,engine).resume_payload({
        "app_id":APP_ID,"continuation_ref":tool["continuation_ref"],
        "decision":decision,
    })
    assert reply.status_code==409,reply.body
    assert reply.body["error"]["code"]=="approval_denied"
    assert engine.execute("SELECT state FROM padiem_web_quote_write_tool_continuations"
                          ).fetchone()["state"]=="consumed"
    b62.close();engine.close()


@pytest.mark.asyncio
async def test_real_durable_core_write_refuses_foreign_or_missing_owner_decision():
    b62,engine,tool,decision=await create_pause()
    b62.execute("DELETE FROM claw_web_xlsx_quote_write_decisions")
    rejected=await service(b62,engine).resume_payload({
        "app_id":APP_ID,"continuation_ref":tool["continuation_ref"],
        "decision":decision,
    })
    assert rejected.status_code==403,rejected.body
    assert engine.execute("SELECT state FROM padiem_web_quote_write_tool_continuations"
                          ).fetchone()["state"]=="active"
    b62.close();engine.close()
