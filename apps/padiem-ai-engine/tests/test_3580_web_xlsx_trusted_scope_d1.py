"""#3580 Engine independently checks real B62 D1 source+run+SHA before P01."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

import pytest

from app.approval_verifier import AuthenticatedFirstPartyApprovalDecisionVerifier
from app.orchestration_service import InMemoryContinuationStore
from app.tool_execution_service import ToolExecutionEngineService
from app.web_xlsx_p01_tool_binding import (
    APP_ID, AGENT_ID, CANONICAL_TOOL, TrustedWebXlsxSelectionScope,
    build_web_xlsx_p01_tool_binding, web_xlsx_p01_arguments,
)
from app.web_xlsx_p01_trusted_scope_d1 import D1WebXlsxTrustedScopeResolver

DOC = "doc_" + "d"*32
SEL = "sel_" + "e"*32
SHA = "a"*64
OWNER = "web_owner_1"
WORKSPACE = "owner:web_owner_1"
RUN = "run_web_p01_1"
FILE = "quote.xlsx"
KEY = f"workspaces/{WORKSPACE}/claw/web-office/{OWNER}/{WORKSPACE}/{DOC}/{SHA}/{FILE}"
MIGRATIONS = Path(__file__).resolve().parents[2] / "padiem-chat" / "migrations"


class Statement:
    def __init__(self, db, sql):
        self.db, self.sql, self.args = db, sql, ()
    def bind(self, *args):
        self.args = args
        return self
    async def first(self):
        row = self.db.execute(self.sql, self.args).fetchone()
        return dict(row) if row is not None else None


class D1:
    def __init__(self, db):
        self.db = db
    def prepare(self, sql):
        return Statement(self.db, sql)


def database():
    db = sqlite3.connect(":memory:", isolation_level=None)
    db.row_factory = sqlite3.Row
    for name in (
        "008_claw_document_metadata.sql", "009_claw_run_history.sql",
        "014_claw_run_history_conversation.sql", "015_claw_run_history_workspace.sql",
        "029_claw_web_xlsx_selection.sql", "030_claw_web_xlsx_p01_requests.sql",
    ):
        db.executescript((MIGRATIONS / name).read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    recent = now.isoformat()
    expiry = (now + timedelta(minutes=25)).isoformat()
    db.execute(
        "INSERT INTO claw_run_history "
        "(id,user_id,run_id,channel,action,title,status,created_at,updated_at,"
        "conversation_id,workspace_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        ("crun1", OWNER, RUN, "web", "office", "Web Office", "running",
         recent, recent, "conv_owner", WORKSPACE),
    )
    db.execute(
        "INSERT INTO claw_document_metadata "
        "(document_id,tenant_id,object_key,filename,media_type,byte_length,"
        "created_at,expires_at,deleted_at) VALUES(?,?,?,?,?,?,?,?,NULL)",
        (DOC, WORKSPACE, KEY, FILE,
         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
         512, recent, expiry),
    )
    db.execute(
        "INSERT INTO claw_web_xlsx_selections "
        "(selection_ref,user_id,workspace_id,document_id,source_sha256,filename,"
        "size_bytes,status,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (SEL, OWNER, WORKSPACE, DOC, SHA, FILE, 512,
         "source_selected_p01_not_started", recent, expiry),
    )
    db.execute(
        "INSERT INTO claw_web_xlsx_p01_requests "
        "(request_ref,selection_ref,user_id,workspace_id,run_id,document_id,"
        "source_sha256,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        ("wpr_" + "b"*32, SEL, OWNER, WORKSPACE, RUN, DOC,
         SHA, "dispatching", recent, recent),
    )
    return db


@pytest.mark.asyncio
async def test_engine_independent_d1_scope_proves_exact_original_metadata():
    db = database()
    resolver = D1WebXlsxTrustedScopeResolver(D1(db))
    scope = await resolver(SEL)
    assert isinstance(scope, TrustedWebXlsxSelectionScope)
    assert (scope.owner_id, scope.workspace_id, scope.run_id,
            scope.document_id, scope.source_sha256) == (
                OWNER, WORKSPACE, RUN, DOC, SHA)
    assert scope.original_immutable and scope.source_active
    assert await resolver("sel_" + "f"*32) is None
    db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", [
    "UPDATE claw_web_xlsx_selections SET user_id='foreign' WHERE selection_ref='" + SEL + "'",
    "UPDATE claw_web_xlsx_selections SET source_sha256='" + "f"*64 + "'",
    "UPDATE claw_web_xlsx_selections SET expires_at='2000-01-01T00:00:00+00:00'",
    "UPDATE claw_web_xlsx_p01_requests SET status='waiting_p01'",
    "UPDATE claw_web_xlsx_p01_requests SET run_id='another_run'",
    "UPDATE claw_document_metadata SET object_key='workspaces/other/secret.xlsx'",
    "UPDATE claw_document_metadata SET deleted_at='2026-10-10T00:00:00+00:00'",
    "UPDATE claw_run_history SET workspace_id='foreign'",
    "UPDATE claw_run_history SET status='completed'",
    "UPDATE claw_run_history SET updated_at='2000-01-01T00:00:00+00:00'",
])
async def test_engine_rejects_any_d1_authority_drift(mutation):
    db = database()
    db.execute(mutation)
    assert await D1WebXlsxTrustedScopeResolver(D1(db))(SEL) is None
    db.close()


@pytest.mark.asyncio
async def test_engine_preflight_denies_foreign_digest_without_creating_pause():
    db = database()
    resolver = D1WebXlsxTrustedScopeResolver(D1(db))
    binding = build_web_xlsx_p01_tool_binding(resolver)
    engine = ToolExecutionEngineService(
        tool_binding_resolver=lambda app: binding if app == APP_ID else None,
        approval_decision_verifier=AuthenticatedFirstPartyApprovalDecisionVerifier(),
        continuation_store=InMemoryContinuationStore(),
    )
    original = await resolver(SEL)
    assert original is not None
    body = {
        "app_id": APP_ID, "agent_id": AGENT_ID,
        "tool_id": CANONICAL_TOOL, "arguments": web_xlsx_p01_arguments(original),
    }
    allowed = await engine.execute_payload(body)
    assert allowed.status_code == 202, allowed.body
    assert allowed.body["tool"]["status"] == "paused"
    for key, bad in (
        ("owner_id", "someone_else"),
        ("workspace_id", "owner:other"),
        ("run_id", "run_wrong"),
        ("document_id", "doc_" + "b"*32),
        ("source_sha256", "f"*64),
    ):
        args = {**body["arguments"], key: bad}
        rejected = await engine.execute_payload({**body, "arguments": args})
        assert rejected.status_code == 403
        assert rejected.body["error"]["code"] == "tool_source_authority_denied"
    db.execute("UPDATE claw_web_xlsx_p01_requests SET status='waiting_p01'")
    revoked = await engine.execute_payload(body)
    assert revoked.status_code == 403
    db.close()


@pytest.mark.asyncio
async def test_engine_preflight_authority_db_unavailable_prevents_pause():
    db = database()
    async def down(_):
        raise RuntimeError("private D1 unavailable")
    binding = build_web_xlsx_p01_tool_binding(down)
    engine = ToolExecutionEngineService(
        tool_binding_resolver=lambda app: binding if app == APP_ID else None,
        approval_decision_verifier=AuthenticatedFirstPartyApprovalDecisionVerifier(),
        continuation_store=InMemoryContinuationStore(),
    )
    source = await D1WebXlsxTrustedScopeResolver(D1(db))(SEL)
    result = await engine.execute_payload({
        "app_id": APP_ID, "agent_id": AGENT_ID,
        "tool_id": CANONICAL_TOOL, "arguments": web_xlsx_p01_arguments(source),
    })
    assert result.status_code == 503
    assert result.body["error"]["code"] == "tool_source_authority_unavailable"
    db.close()


@pytest.mark.asyncio
async def test_separate_pre_pause_and_post_approved_d1_status_recheck():
    from padiem_ai_core import ToolAuthorizationContext, ToolInvocation, ToolRuntimeError
    db = database()
    first = D1WebXlsxTrustedScopeResolver(D1(db))
    approved_only = D1WebXlsxTrustedScopeResolver(
        D1(db), required_status="waiting_p01",
    )
    assert await first(SEL) is not None
    assert await approved_only(SEL) is None
    binding = build_web_xlsx_p01_tool_binding(
        first, approved_selection_resolver=approved_only,
    )
    scope = await first(SEL)
    auth = binding.resolve_authority(AGENT_ID)
    args = web_xlsx_p01_arguments(scope)
    confirmed = ToolAuthorizationContext(
        app_id=APP_ID, agent_id=auth.compiled.runtime_profile.id,
        granted_auth_scopes=("workspace.xlsx.original.read.intent",),
        user_confirmed_tools=("workspace.xlsx.confirm_original_read",),
    )
    invocation = ToolInvocation(
        tool_id="workspace.xlsx.confirm_original_read", arguments=args,
    )
    # Engine user confirmation alone cannot prematurely read a source while
    # B62 still has an uncommitted/uncertain dispatch.
    with pytest.raises(ToolRuntimeError):
        await binding.tool_runtime.execute(
            invocation, auth.compiled.runtime_profile, confirmed,
        )
    db.execute("UPDATE claw_web_xlsx_p01_requests SET status='waiting_p01'")
    assert await first(SEL) is None
    assert await approved_only(SEL) is not None
    result = await binding.tool_runtime.execute(
        invocation, auth.compiled.runtime_profile, confirmed,
    )
    assert result.output["p01_intent_confirmed"] is True
    assert result.output["read_executed"] is False
    assert result.output["workcopy_created"] is False
    # Even on the approved invocation, a missing original stops processing.
    db.execute("UPDATE claw_document_metadata SET deleted_at=? WHERE document_id=?",
               (datetime.now(timezone.utc).isoformat(), DOC))
    with pytest.raises(ToolRuntimeError):
        await binding.tool_runtime.execute(
            invocation, auth.compiled.runtime_profile, confirmed,
        )
    db.close()
