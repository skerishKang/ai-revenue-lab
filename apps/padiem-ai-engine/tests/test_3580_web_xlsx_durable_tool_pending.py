"""#3580: real SQLite Engine ToolInvocation durability and cross-isolate CAS."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from padiem_ai_core.tool_runtime import ToolAuthorizationContext
from app.tool_execution_service import ToolExecutionEngineService
from app.web_xlsx_tool_pending_d1 import D1WebXlsxToolPendingStore
from app.web_xlsx_p01_tool_binding import (
    APP_ID, AGENT_ID, CANONICAL_TOOL, RUNTIME_TOOL,
    TrustedWebXlsxSelectionScope, build_web_xlsx_p01_tool_binding,
    web_xlsx_p01_arguments,
)
from padiem_ai_core.agent_approval import VerifiedApprovalDecision


class TestVerifier:
    def verify(self, submission, *, pause, app_id):
        return VerifiedApprovalDecision(
            decision_id=submission.decision_id, pause_id=submission.pause_id,
            outcome=submission.outcome, authority_ref=submission.authority_ref,
            evidence_ref=submission.evidence_ref, decided_at=submission.decided_at,
        )


class SQLiteD1:
    def __init__(self, db):
        self.db = db

    def prepare(self, sql):
        return SQLiteStmt(self.db, sql)


class SQLiteStmt:
    def __init__(self, db, sql):
        self.db, self.sql, self.args = db, sql, ()

    def bind(self, *args):
        self.args = args
        return self

    async def first(self):
        row = self.db.execute(self.sql, self.args).fetchone()
        return dict(row) if row is not None else None

    async def run(self):
        self.db.execute(self.sql, self.args)
        return {"success": True}


def database():
    db = sqlite3.connect(":memory:", isolation_level=None)
    db.row_factory = sqlite3.Row
    db.executescript((
        Path(__file__).resolve().parents[1] /
        "migrations" / "0009_web_xlsx_tool_continuations.sql"
    ).read_text(encoding="utf-8"))
    return db


SCOPE = TrustedWebXlsxSelectionScope(
    owner_id="owner_web_a", workspace_id="owner:web_a",
    run_id="run_web_55", selection_ref="sel_"+"a"*32,
    document_id="doc_"+"b"*32, source_sha256="c"*64,
    original_immutable=True, source_active=True,
)


def service(db, *, grant=False, original=SCOPE):
    async def read_metadata(ref):
        return original if ref == original.selection_ref else None

    binding = build_web_xlsx_p01_tool_binding(read_metadata)
    if grant:
        identity = binding.resolve_authority(AGENT_ID).authorization
        binding = replace(binding, authorization_provider=lambda _: ToolAuthorizationContext(
            app_id=APP_ID, agent_id=identity.agent_id,
            granted_auth_scopes=identity.granted_auth_scopes,
            user_confirmed_tools=(RUNTIME_TOOL,),
        ))
    return ToolExecutionEngineService(
        tool_binding_resolver=lambda app: binding if app == APP_ID else None,
        approval_decision_verifier=TestVerifier(),
        continuation_store=D1WebXlsxToolPendingStore(SQLiteD1(db)),
    )


async def pause(tool_service):
    resp = await tool_service.execute_payload({
        "app_id": APP_ID, "agent_id": AGENT_ID,
        "tool_id": CANONICAL_TOOL,
        "arguments": web_xlsx_p01_arguments(SCOPE),
    })
    assert resp.status_code == 202, resp.body
    return resp.body["tool"]


def decision(tool, outcome="denied"):
    return {
        "decision_id": "decision_3580_web",
        "pause_id": tool["approval_pause"]["continuation_id"],
        "outcome": outcome,
        "authority_ref": "first_party_owner",
        "evidence_ref": "first_party_session",
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }


@pytest.mark.asyncio
async def test_real_pause_is_single_durable_row_with_exact_tool_hash():
    db = database()
    one = service(db)
    tool = await pause(one)
    row = db.execute("SELECT * FROM padiem_web_xlsx_tool_continuations").fetchone()
    assert row["state"] == "active"
    assert row["continuation_ref"] == tool["continuation_ref"]
    assert row["pause_id"] == tool["approval_pause"]["continuation_id"]
    from app.continuation_d1 import _pause_from_json
    assert row["invocation_sha256"] == _pause_from_json(row["pause_json"]).invocation_sha256
    args = json.loads(row["invocation_json"])
    assert args["source_sha256"] == SCOPE.source_sha256
    assert args["selection_ref"] == SCOPE.selection_ref
    assert not any(x in json.dumps(dict(row)) for x in ("google_api_key", "customer_bytes"))
    assert one._pending == {}  # cross-isolate only; no RAM authority
    new_isolate = service(db)
    pending = await new_isolate._continuation_call(
        "load_tool_pending", app_id=APP_ID, continuation_ref=tool["continuation_ref"],
    )
    assert pending["arguments"] == web_xlsx_p01_arguments(SCOPE)
    assert new_isolate._pending == {}
    db.close()


@pytest.mark.asyncio
async def test_cross_isolate_denial_consumes_once_without_tool_work():
    db = database()
    tool = await pause(service(db))
    fresh_worker = service(db)
    req = {
        "app_id": APP_ID, "continuation_ref": tool["continuation_ref"],
        "decision": decision(tool),
    }
    refused = await fresh_worker.resume_payload(req)
    assert refused.status_code == 409
    assert refused.body["error"]["code"] == "approval_denied"
    row = db.execute("SELECT state FROM padiem_web_xlsx_tool_continuations").fetchone()
    assert row["state"] == "consumed"
    replay = await service(db).resume_payload(req)
    assert replay.status_code == 409
    db.close()


@pytest.mark.asyncio
async def test_cross_isolate_approved_grant_is_not_a_wire_self_grant():
    db = database()
    tool = await pause(service(db))
    req = {
        "app_id": APP_ID, "continuation_ref": tool["continuation_ref"],
        "decision": decision(tool, "approved"),
    }
    # Verifier alone must never bypass Core's user-confirmation gate.
    blocked = await service(db).resume_payload(req)
    assert blocked.status_code in (403, 409)
    assert db.execute("SELECT state FROM padiem_web_xlsx_tool_continuations").fetchone()["state"] == "active"
    # In this isolated test ONLY, a server-side grant provider represents
    # the independently verified first-party decision not yet wired for prod.
    approved = await service(db, grant=True).resume_payload(req)
    assert approved.status_code == 200, approved.body
    assert approved.body["tool"]["status"] == "completed"
    assert approved.body["tool"]["output"]["read_executed"] is False
    assert db.execute("SELECT state FROM padiem_web_xlsx_tool_continuations").fetchone()["state"] == "consumed"
    again = await service(db, grant=True).resume_payload(req)
    assert again.status_code == 409
    db.close()


@pytest.mark.asyncio
async def test_same_continuation_cannot_be_claimed_twice_or_cross_app():
    db = database()
    tool = await pause(service(db))
    store1 = D1WebXlsxToolPendingStore(SQLiteD1(db))
    store2 = D1WebXlsxToolPendingStore(SQLiteD1(db))
    with pytest.raises(Exception):
        await store2.resolve(app_id="other-app", continuation_ref=tool["continuation_ref"])
    claimed = await store1.claim(app_id=APP_ID, continuation_ref=tool["continuation_ref"])
    assert claimed.claim_token
    with pytest.raises(Exception):
        await store2.claim(app_id=APP_ID, continuation_ref=tool["continuation_ref"])
    with pytest.raises(Exception):
        await store2.commit(app_id=APP_ID, continuation_ref=tool["continuation_ref"], claim_token="wrong")
    await store2.release(app_id=APP_ID, continuation_ref=tool["continuation_ref"],
                         claim_token=claimed.claim_token)
    again = await store2.claim(app_id=APP_ID, continuation_ref=tool["continuation_ref"])
    await store1.commit(app_id=APP_ID, continuation_ref=tool["continuation_ref"],
                        claim_token=again.claim_token)
    with pytest.raises(Exception):
        await store1.resolve(app_id=APP_ID, continuation_ref=tool["continuation_ref"])
    db.close()


@pytest.mark.asyncio
async def test_corrupted_or_rebound_source_hash_never_rehydrates():
    for column, mutation in (
        ("invocation_sha256", "f"*64),
        ("invocation_json", json.dumps({**web_xlsx_p01_arguments(SCOPE), "run_id": "foreign"})),
        ("canonical_tool_id", "tool:other:wrong@1"),
    ):
        db = database()
        tool = await pause(service(db))
        db.execute(f"UPDATE padiem_web_xlsx_tool_continuations SET {column}=?", (mutation,))
        with pytest.raises(Exception):
            await D1WebXlsxToolPendingStore(SQLiteD1(db)).load_tool_pending(
                app_id=APP_ID, continuation_ref=tool["continuation_ref"],
            )
        db.close()


@pytest.mark.asyncio
async def test_missing_engine_migration_never_creates_pause():
    db = sqlite3.connect(":memory:", isolation_level=None)
    db.row_factory = sqlite3.Row
    failed = await service(db).execute_payload({
        "app_id": APP_ID, "agent_id": AGENT_ID, "tool_id": CANONICAL_TOOL,
        "arguments": web_xlsx_p01_arguments(SCOPE),
    })
    assert failed.status_code == 503
    db.close()
