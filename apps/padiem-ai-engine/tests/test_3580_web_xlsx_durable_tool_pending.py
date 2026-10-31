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


