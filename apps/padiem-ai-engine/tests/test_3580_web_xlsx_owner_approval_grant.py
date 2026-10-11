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
async def test_real_core_owner_only_confirmation_across_new_engine_isolate():
    b62, engine, tool = await prepared_pause()
    record_decision(b62, tool)
    result = await resume(b62, engine, tool)
    assert result.status_code == 200, result.body
    assert result.body["tool"]["status"] == "completed"
    assert result.body["tool"]["output"]["p01_intent_confirmed"] is True
    assert result.body["tool"]["output"]["read_executed"] is False
    assert result.body["tool"]["output"]["workcopy_created"] is False
    assert engine.execute(
        "SELECT state FROM padiem_web_xlsx_tool_continuations"
    ).fetchone()["state"] == "consumed"
    assert (await resume(b62, engine, tool)).status_code == 409
    b62.close()
    engine.close()


@pytest.mark.asyncio
async def test_no_receipt_cannot_mint_core_grant_but_real_receipt_can():
    b62, engine, tool = await prepared_pause()
    rejected = await resume(b62, engine, tool)
    assert rejected.status_code == 403
    assert engine.execute(
        "SELECT state FROM padiem_web_xlsx_tool_continuations"
    ).fetchone()["state"] == "active"
    record_decision(b62, tool)
    allowed = await resume(b62, engine, tool)
    assert allowed.status_code == 200
    b62.close()
    engine.close()


@pytest.mark.asyncio
async def test_denial_consumes_without_grant_or_work():
    b62, engine, tool = await prepared_pause()
    record_decision(b62, tool, outcome="deny")
    denied = await resume(b62, engine, tool, submission(tool, outcome="denied"))
    assert denied.status_code == 409
    assert denied.body["error"]["code"] == "approval_denied"
    assert engine.execute(
        "SELECT state FROM padiem_web_xlsx_tool_continuations"
    ).fetchone()["state"] == "consumed"
    b62.close()
    engine.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", [
    "owner", "pause", "sha", "outcome", "state",
    "authority_ref", "evidence_ref", "decision_id", "original",
])
async def test_owner_receipt_or_first_party_decision_mutation_denied(tamper):
    b62, engine, tool = await prepared_pause()
    record_decision(b62, tool)
    wire = submission(tool)
    if tamper == "owner":
        b62.execute(
            "UPDATE claw_web_xlsx_p01_decision_receipts SET user_id='other_owner'"
        )
    elif tamper == "pause":
        b62.execute(
            "UPDATE claw_web_xlsx_p01_decision_receipts SET pause_id='pause:" + "f"*24 + "'"
        )
    elif tamper == "sha":
        b62.execute(
            "UPDATE claw_web_xlsx_p01_decision_receipts SET source_sha256='" + "f"*64 + "'"
        )
    elif tamper == "outcome":
        b62.execute(
            "UPDATE claw_web_xlsx_p01_decision_receipts SET outcome='deny'"
        )
    elif tamper == "state":
        b62.execute(
            "UPDATE claw_web_xlsx_p01_decision_receipts SET state='denied'"
        )
    elif tamper == "original":
        b62.execute("UPDATE claw_document_metadata SET deleted_at=?",
                    (datetime.now(timezone.utc).isoformat(),))
    else:
        wire[tamper] = "forged"
    result = await resume(b62, engine, tool, wire)
    assert result.status_code in (403, 409), (tamper, result.body)
    assert engine.execute(
        "SELECT state FROM padiem_web_xlsx_tool_continuations"
    ).fetchone()["state"] == "active"
    b62.close()
    engine.close()


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


@pytest.mark.asyncio
async def test_denial_without_signed_owner_receipt_cannot_consume_tool_pause():
    b62, engine, tool = await prepared_pause()
    denial = submission(tool, outcome="denied")
    untrusted = await resume(b62, engine, tool, denial)
    assert untrusted.status_code == 403, untrusted.body
    assert engine.execute(
        "SELECT state FROM padiem_web_xlsx_tool_continuations"
    ).fetchone()["state"] == "active"
    record_decision(b62, tool, outcome="deny")
    b62.execute(
        "UPDATE claw_web_xlsx_p01_decision_receipts SET user_id='impostor'"
    )
    tampered = await resume(b62, engine, tool, denial)
    assert tampered.status_code == 403, tampered.body
    b62.execute(
        "UPDATE claw_web_xlsx_p01_decision_receipts SET user_id=?",
        (OWNER,),
    )
    authorized = await resume(b62, engine, tool, denial)
    assert authorized.status_code == 409
    assert authorized.body["error"]["code"] == "approval_denied"
    assert engine.execute(
        "SELECT state FROM padiem_web_xlsx_tool_continuations"
    ).fetchone()["state"] == "consumed"
    b62.close()
    engine.close()
