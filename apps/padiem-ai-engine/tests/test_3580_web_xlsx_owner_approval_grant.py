"""#3580: actual Core P01 consent granted ONLY for real signed-in B62 owner D1 receipt."""
from __future__ import annotations

import hashlib
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_3580_web_xlsx_trusted_scope_d1 import (
    database as b62_database, D1 as B62D1, OWNER, WORKSPACE, RUN, SEL, DOC, SHA,
)
from test_3580_web_xlsx_durable_tool_pending import (
    database as engine_database, SQLiteD1,
)
from app.approval_verifier import AuthenticatedFirstPartyApprovalDecisionVerifier
from app.tool_execution_service import ToolExecutionEngineService
from app.web_xlsx_p01_owner_approval_d1 import D1WebXlsxOwnerApprovalGrant
from app.web_xlsx_p01_trusted_scope_d1 import D1WebXlsxTrustedScopeResolver
from app.web_xlsx_p01_tool_binding import (
    APP_ID, AGENT_ID, CANONICAL_TOOL, build_web_xlsx_p01_tool_binding,
    web_xlsx_p01_arguments,
)
from app.web_xlsx_tool_pending_d1 import D1WebXlsxToolPendingStore

MIGRATION = Path(__file__).resolve().parents[2] / "padiem-chat" / "migrations" / "031_claw_web_xlsx_p01_decision_receipts.sql"


def service(b62, engine):
    reader = B62D1(b62)
    before = D1WebXlsxTrustedScopeResolver(reader, required_status="dispatching")
    after = D1WebXlsxTrustedScopeResolver(reader, required_status="waiting_p01")
    binding = build_web_xlsx_p01_tool_binding(
        before, approved_selection_resolver=after,
    )
    return ToolExecutionEngineService(
        tool_binding_resolver=lambda app: binding if app == APP_ID else None,
        approval_decision_verifier=AuthenticatedFirstPartyApprovalDecisionVerifier(),
        continuation_store=D1WebXlsxToolPendingStore(SQLiteD1(engine)),
        web_xlsx_owner_approval_grant=D1WebXlsxOwnerApprovalGrant(reader),
    )


async def prepared_pause():
    b62, engine = b62_database(), engine_database()
    b62.executescript(MIGRATION.read_text(encoding="utf-8"))
    src = await D1WebXlsxTrustedScopeResolver(B62D1(b62))(SEL)
    assert src is not None
    emitted = await service(b62, engine).execute_payload({
        "app_id": APP_ID, "agent_id": AGENT_ID,
        "tool_id": CANONICAL_TOOL, "arguments": web_xlsx_p01_arguments(src),
    })
    assert emitted.status_code == 202, emitted.body
    tool = emitted.body["tool"]
    pause = tool["approval_pause"]["continuation_id"]
    continuation = tool["continuation_ref"]
    b62.execute(
        "UPDATE claw_web_xlsx_p01_requests "
        "SET status='waiting_p01',pause_id=?,continuation_ref=?,engine_run_id=?,pause_expires_at=?",
        (pause, continuation, tool["run_id"], tool["approval_pause"]["expires_at"]),
    )
    return b62, engine, tool


def record_decision(b62, tool, *, outcome="approve"):
    b62.execute(
        "INSERT INTO claw_web_xlsx_p01_decision_receipts "
        "(request_ref,selection_ref,user_id,workspace_id,run_id,source_sha256,"
        "pause_id,outcome,state,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,'dispatching',?,?)",
        ("wpr_" + "b"*32, SEL, OWNER, WORKSPACE, RUN, SHA,
         tool["approval_pause"]["continuation_id"], outcome,
         datetime.now(timezone.utc).isoformat(),
         datetime.now(timezone.utc).isoformat()),
    )


def submission(tool, *, outcome="approved"):
    pause = tool["approval_pause"]["continuation_id"]
    decision_id = "decision_b54_" + hashlib.sha256(
        f"{OWNER}|{pause}|{outcome}".encode()
    ).hexdigest()[:32]
    return {
        "decision_id": decision_id,
        "pause_id": pause,
        "outcome": outcome,
        "authority_ref": "b54_session:" + OWNER,
        "evidence_ref": "b54_decision:" + decision_id,
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }


async def resume(b62, engine, tool, data=None):
    return await service(b62, engine).resume_payload({
        "app_id": APP_ID, "continuation_ref": tool["continuation_ref"],
        "decision": data if data is not None else submission(tool),
    })


@pytest.mark.asyncio
async def test_engine_rejects_grant_without_first_party_verifier():
    from test_3580_web_xlsx_durable_tool_pending import TestVerifier
    b62, engine = b62_database(), engine_database()
    binding = build_web_xlsx_p01_tool_binding(lambda _x: None)
    with pytest.raises(ValueError):
        ToolExecutionEngineService(
            tool_binding_resolver=lambda _: binding,
            approval_decision_verifier=TestVerifier(),
            continuation_store=D1WebXlsxToolPendingStore(SQLiteD1(engine)),
            web_xlsx_owner_approval_grant=D1WebXlsxOwnerApprovalGrant(B62D1(b62)),
        )
    b62.close()
    engine.close()


