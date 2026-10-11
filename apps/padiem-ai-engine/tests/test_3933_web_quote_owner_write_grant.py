"""Actual independent Engine Core pause + B62 owner WRITE D1 authorization proof."""
from __future__ import annotations

import hashlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from padiem_ai_core.agent_approval import (
    ApprovalPause, ApprovalOutcome, ApprovalRequirement,
    VerifiedApprovalDecision, tool_invocation_digest,
)
from padiem_ai_core.tool_runtime import ToolInvocation

sys.path.insert(0, str(Path(__file__).parent))
from test_3933_web_quote_write_core import (
    database, D1, SEL, OWNER, WORKSPACE, RUN, COPY,
    NAME, AMOUNT, EDIT_SHA,
)
from app.web_xlsx_quote_write_tool_binding import (
    RUNTIME_TOOL, quote_write_arguments,
)
from app.web_xlsx_quote_write_scope_d1 import D1WebQuoteWriteScopeResolver
from app.web_xlsx_quote_write_owner_approval_d1 import (
    D1WebQuoteOwnerWriteApprovalGrant,
)

PAUSE = "pause:" + "b"*32
CONT = "cont_" + "c"*36


async def prepared(outcome="approve"):
    db = database()
    path = (Path(__file__).resolve().parents[2] / "padiem-chat"
            / "migrations" / "033_claw_web_xlsx_quote_write_decisions.sql")
    db.executescript(path.read_text(encoding="utf-8"))
    scope = await D1WebQuoteWriteScopeResolver(D1(db))(SEL)
    args = quote_write_arguments(scope)
    inv = ToolInvocation(tool_id=RUNTIME_TOOL, arguments=args)
    now = datetime.now(timezone.utc)
    pause = ApprovalPause(
        pause_id=PAUSE, run_id=RUN,
        agent_runtime_id="agent-runtime:1234567890abcdef12345678",
        tool_id=RUNTIME_TOOL, invocation_sha256=tool_invocation_digest(inv),
        requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=1, created_at=now - timedelta(seconds=2),
        expires_at=now + timedelta(minutes=5),
    )
    db.execute(
        "INSERT INTO claw_web_xlsx_quote_write_decisions "
        "(selection_ref,user_id,workspace_id,run_id,source_document_id,"
        "source_sha256,workcopy_document_id,edit_sha256,pause_id,"
        "continuation_ref,outcome,state,created_at,updated_at) "
        "SELECT selection_ref,user_id,workspace_id,run_id,source_document_id,"
        "source_sha256,workcopy_document_id,edit_sha256,?,?,?,'dispatching',?,?"
        " FROM claw_web_xlsx_quote_edit_receipts WHERE selection_ref=?",
        (PAUSE,CONT,outcome,now.isoformat(),now.isoformat(),SEL),
    )
    outcome_name = "approved" if outcome == "approve" else "denied"
    did = "decision_b54_" + hashlib.sha256(
        f"{OWNER}|{PAUSE}|{outcome_name}".encode()).hexdigest()[:32]
    dec = VerifiedApprovalDecision(
        decision_id=did, pause_id=PAUSE,
        outcome=(ApprovalOutcome.APPROVED if outcome == "approve"
                 else ApprovalOutcome.DENIED),
        authority_ref="b54_session:"+OWNER,
        evidence_ref="b54_decision:"+did, decided_at=now,
    )
    return db,pause,dec,inv


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome",["approve","deny"])
async def test_engine_independently_matches_actual_paused_owner_write_decision(outcome):
    db,pause,decision,inv=await prepared(outcome)
    verifier=D1WebQuoteOwnerWriteApprovalGrant(D1(db))
    assert await verifier(pause=pause,decision=decision,invocation=inv,
                          continuation_ref=CONT) is True
    db.execute("UPDATE claw_web_xlsx_quote_write_decisions SET state='confirmed'")
    assert await verifier(pause=pause,decision=decision,invocation=inv,
                          continuation_ref=CONT) is False
    db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper",[
    "DELETE FROM claw_web_xlsx_quote_write_decisions",
    "UPDATE claw_web_xlsx_quote_write_decisions SET user_id='foreign'",
    "UPDATE claw_web_xlsx_quote_write_decisions SET workspace_id='foreign'",
    "UPDATE claw_web_xlsx_quote_write_decisions SET run_id='run_foreign'",
    "UPDATE claw_web_xlsx_quote_write_decisions SET source_sha256='"+ "e"*64+"'",
    "UPDATE claw_web_xlsx_quote_write_decisions SET edit_sha256='"+ "f"*64+"'",
    "UPDATE claw_web_xlsx_quote_write_decisions SET workcopy_document_id='doc_"+ "f"*32+"'",
    "UPDATE claw_web_xlsx_quote_write_decisions SET pause_id='pause:"+ "e"*32+"'",
    "UPDATE claw_web_xlsx_quote_write_decisions SET continuation_ref='cont_foreign'",
    "UPDATE claw_web_xlsx_quote_write_decisions SET outcome='deny'",
    "UPDATE claw_web_xlsx_quote_write_decisions SET state='denied'",
    "UPDATE claw_web_xlsx_quote_edit_receipts SET supply_amount=99200010",
    "UPDATE claw_run_history SET status='completed'",
])
async def test_d1_owner_write_drift_never_grants_core_write(tamper):
    db,pause,decision,inv=await prepared()
    db.execute(tamper)
    assert await D1WebQuoteOwnerWriteApprovalGrant(D1(db))(
        pause=pause,decision=decision,invocation=inv,
        continuation_ref=CONT) is False
    db.close()


@pytest.mark.asyncio
async def test_wrong_pause_digest_continuation_or_first_party_decision_cannot_mint_write():
    from dataclasses import replace
    db,pause,dec,inv=await prepared()
    guard=D1WebQuoteOwnerWriteApprovalGrant(D1(db))
    assert not await guard(pause=pause,decision=replace(dec,decision_id="forged"),
                           invocation=inv,continuation_ref=CONT)
    assert not await guard(pause=pause,decision=replace(dec,authority_ref="browser"),
                           invocation=inv,continuation_ref=CONT)
    assert not await guard(pause=pause,decision=dec,
                           invocation=inv,continuation_ref="cont_wrong")
    assert not await guard(pause=replace(pause,invocation_sha256="f"*64),
                           decision=dec,invocation=inv,continuation_ref=CONT)
    altered=ToolInvocation(tool_id=RUNTIME_TOOL,
                           arguments={**inv.arguments,"edit_sha256":"f"*64})
    assert not await guard(pause=pause,decision=dec,
                           invocation=altered,continuation_ref=CONT)
    db.close()
