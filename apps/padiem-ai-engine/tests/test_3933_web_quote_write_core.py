"""#3933: Core WRITE ToolSpec is distinct from original READ grant.

Synthetic B62 private D1 fixture; no browser/user password, no production DB,
no claim that a Core approval is granted by the current Worker.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).parent))

import pytest
from padiem_ai_core import ToolInvocation, ToolRuntimeError
from padiem_ai_core.tool_runtime import ToolAuthorizationContext

from app.web_xlsx_quote_write_tool_binding import (
    APP_ID, AGENT_ID, CANONICAL_TOOL, RUNTIME_TOOL, SCOPE,
    TrustedQuoteWriteScope, build_web_quote_write_tool_binding,
    quote_edit_sha256, quote_write_arguments, quote_write_spec,
    with_web_quote_write_tool_binding, PRODUCTION_HARK_WEB_QUOTE_WRITE_COMPOSED,
)
from app.web_xlsx_quote_write_scope_d1 import D1WebQuoteWriteScopeResolver

from test_3580_web_xlsx_trusted_scope_d1 import (
    database as existing_database, D1, MIGRATIONS,
    OWNER, WORKSPACE, RUN, DOC, SEL, SHA, FILE,
)

COPY = "doc_" + "c"*32
NAME = "Gwangju University"
AMOUNT = 99_200_000
EDIT_SHA = quote_edit_sha256(NAME, AMOUNT)


def database():
    db = existing_database()
    for name in ("031_claw_web_xlsx_p01_decision_receipts.sql",
                 "032_claw_web_xlsx_quote_edit_receipts.sql"):
        db.executescript((MIGRATIONS / name).read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    current, expiry = now.isoformat(), (now + timedelta(minutes=25)).isoformat()
    db.execute(
        "UPDATE claw_web_xlsx_p01_requests SET status='waiting_p01'"
    )
    db.execute(
        "INSERT INTO claw_web_xlsx_p01_decision_receipts "
        "(request_ref,selection_ref,user_id,workspace_id,run_id,source_sha256,"
        "pause_id,outcome,state,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        ("wpr_" + "b"*32, SEL, OWNER, WORKSPACE, RUN, SHA,
         "pause_test_3933", "approve", "confirmed", current, current),
    )
    key = (f"workspaces/{WORKSPACE}/claw/web-office-workcopies/"
           f"{OWNER}/{WORKSPACE}/{RUN}/{DOC}/{COPY}/{SHA}")
    db.execute(
        "INSERT INTO claw_document_metadata "
        "(document_id,tenant_id,object_key,filename,media_type,byte_length,"
        "created_at,expires_at,deleted_at) VALUES(?,?,?,?,?,?,?,?,NULL)",
        (COPY, WORKSPACE, key, FILE,
         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
         512, current, expiry),
    )
    db.execute(
        "INSERT INTO claw_web_xlsx_quote_edit_receipts "
        "(selection_ref,user_id,workspace_id,run_id,source_document_id,"
        "source_sha256,workcopy_document_id,edit_sha256,school_name,"
        "supply_amount,state,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,'dispatching',?,?)",
        (SEL, OWNER, WORKSPACE, RUN, DOC, SHA, COPY, EDIT_SHA,
         NAME, AMOUNT, current, current),
    )
    return db


@pytest.mark.asyncio
async def test_distinct_engine_d1_write_scope_uses_only_authentic_reserved_edit():
    db = database()
    scope = await D1WebQuoteWriteScopeResolver(D1(db))(SEL)
    assert isinstance(scope, TrustedQuoteWriteScope)
    assert scope.workcopy_document_id == COPY
    assert scope.edit_sha256 == EDIT_SHA
    assert scope.source_sha256 == scope.workcopy_sha256
    assert (scope.write_reserved, scope.run_active, scope.workcopy_private) == (True, True, True)
    assert quote_write_arguments(scope)["operation"] == "xlsx.quote.revise_workcopy"
    assert await D1WebQuoteWriteScopeResolver(D1(db))("sel_"+"f"*32) is None
    db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", [
    "UPDATE claw_web_xlsx_quote_edit_receipts SET state='confirmed',"
    "revision_document_id='doc_"+"e"*32+"',revision_sha256='"+SHA+"'",
    "UPDATE claw_web_xlsx_quote_edit_receipts SET edit_sha256='"+ "f"*64+"'",
    "UPDATE claw_web_xlsx_quote_edit_receipts SET user_id='foreign'",
    "UPDATE claw_web_xlsx_quote_edit_receipts SET supply_amount=99200010",
    "UPDATE claw_web_xlsx_quote_edit_receipts SET workcopy_document_id='doc_"+"f"*32+"'",
    "UPDATE claw_web_xlsx_p01_decision_receipts SET outcome='deny',state='denied'",
    "UPDATE claw_web_xlsx_p01_decision_receipts SET user_id='foreign'",
    "UPDATE claw_web_xlsx_p01_requests SET status='dispatching'",
    "UPDATE claw_run_history SET status='completed'",
    "UPDATE claw_run_history SET updated_at='2000-01-01T00:00:00+00:00'",
    "UPDATE claw_web_xlsx_selections SET expires_at='2000-01-01T00:00:00+00:00'",
    "UPDATE claw_document_metadata SET deleted_at='2026-10-01T00:00:00+00:00' WHERE document_id='"+COPY+"'",
    "UPDATE claw_document_metadata SET object_key='workspaces/foreign/x' WHERE document_id='"+COPY+"'",
    "UPDATE claw_document_metadata SET tenant_id='foreign' WHERE document_id='"+DOC+"'",
])
async def test_engines_write_authority_fails_closed_on_private_d1_drift(mutation):
    db = database()
    db.execute(mutation)
    assert await D1WebQuoteWriteScopeResolver(D1(db))(SEL) is None
    db.close()


@pytest.mark.asyncio
async def test_exact_core_write_tool_pauses_requires_user_confirmation_and_rechecks_d1():
    db = database()
    resolver = D1WebQuoteWriteScopeResolver(D1(db))
    scope = await resolver(SEL)
    binding = build_web_quote_write_tool_binding(resolver)
    spec = quote_write_spec()
    assert spec.side_effect.value == "write"
    assert spec.approval_policy.value == "user_confirmation"
    assert spec.auth_scope == (SCOPE,)
    assert binding.registry.canonical_tool_ids == (CANONICAL_TOOL,)
    authority = binding.resolve_authority(AGENT_ID)
    invocation = ToolInvocation(tool_id=RUNTIME_TOOL, arguments=quote_write_arguments(scope))
    with pytest.raises(ToolRuntimeError) as missing:
        await binding.tool_runtime.execute(
            invocation, authority.compiled.runtime_profile, authority.authorization)
    assert missing.value.code == "tool_user_confirmation_required"
    verified = ToolAuthorizationContext(
        app_id=APP_ID, agent_id=authority.compiled.runtime_profile.id,
        granted_auth_scopes=(SCOPE,), user_confirmed_tools=(RUNTIME_TOOL,),
    )
    result = await binding.tool_runtime.execute(
        invocation, authority.compiled.runtime_profile, verified,
    )
    assert result.output["ok"] is True
    assert result.output["core_tool_completed"] is True
    assert result.output["edit_sha256"] == EDIT_SHA
    assert result.output["pdf_exported"] is False
    assert result.output["workcopy_sha256"] == SHA
    db.execute("UPDATE claw_web_xlsx_quote_edit_receipts SET state='confirmed',"
               "revision_document_id=?,revision_sha256=?",
               ("doc_"+"e"*32, SHA))
    with pytest.raises(ToolRuntimeError):
        await binding.tool_runtime.execute(invocation, authority.compiled.runtime_profile, verified)
    db.close()


@pytest.mark.asyncio
async def test_core_denies_changed_arguments_and_read_only_grant_cannot_write():
    db = database()
    resolver = D1WebQuoteWriteScopeResolver(D1(db))
    scope = await resolver(SEL)
    binding = build_web_quote_write_tool_binding(resolver)
    authority = binding.resolve_authority(AGENT_ID)
    read_only = ToolAuthorizationContext(
        app_id=APP_ID, agent_id=authority.compiled.runtime_profile.id,
        granted_auth_scopes=(SCOPE,),
        user_confirmed_tools=("workspace.xlsx.confirm_original_read",),
    )
    inv = ToolInvocation(tool_id=RUNTIME_TOOL, arguments=quote_write_arguments(scope))
    with pytest.raises(ToolRuntimeError) as denial:
        await binding.tool_runtime.execute(inv, authority.compiled.runtime_profile, read_only)
    assert denial.value.code == "tool_user_confirmation_required"
    exact = replace(read_only, user_confirmed_tools=(RUNTIME_TOOL,))
    for patch in (
        {"school_name": "Foreign"},
        {"edit_sha256": "e"*64},
        {"workcopy_document_id": "doc_"+"d"*32},
        {"owner_id": "owner_foreign"},
        {"source_sha256": "b"*64},
    ):
        with pytest.raises(ToolRuntimeError):
            await binding.tool_runtime.execute(
                ToolInvocation(tool_id=RUNTIME_TOOL, arguments={**inv.arguments, **patch}),
                authority.compiled.runtime_profile, exact,
            )
    for bad in ({"drive_write": True}, {"overwrite_original": True},
                {"pdf_exported": True}, {"read_content": True},
                {"local_pc_access": True}, {"operation": "delete"},
                {"original_immutable": False}):
        with pytest.raises(ToolRuntimeError) as exc:
            await binding.tool_runtime.execute(
                ToolInvocation(tool_id=RUNTIME_TOOL, arguments={**inv.arguments, **bad}),
                authority.compiled.runtime_profile, exact,
            )
        assert exc.value.code == "invalid_tool_arguments"
    db.close()


def test_engine_write_registration_requires_host_owned_b62_d1_resolver():
    existing = lambda _: None
    assert PRODUCTION_HARK_WEB_QUOTE_WRITE_COMPOSED is False
    assert with_web_quote_write_tool_binding(existing) is existing
    assert with_web_quote_write_tool_binding(existing, enabled=True) is existing
    assert with_web_quote_write_tool_binding(
        existing, scope_resolver=lambda _: None) is existing
    resolved = with_web_quote_write_tool_binding(
        existing, enabled=True, scope_resolver=lambda _: None)
    assert resolved(APP_ID).registry.canonical_tool_ids == (CANONICAL_TOOL,)
    assert resolved("other") is None
    assert quote_edit_sha256(NAME, AMOUNT) == EDIT_SHA
    with pytest.raises(ValueError):
        quote_edit_sha256("=HYPERLINK()", AMOUNT)
    with pytest.raises(ValueError):
        quote_edit_sha256(NAME, 1001)

@pytest.mark.asyncio
async def test_engine_does_not_resume_write_without_separate_durable_owner_approval():
    from app.approval_verifier import AuthenticatedFirstPartyApprovalDecisionVerifier
    from app.orchestration_service import InMemoryContinuationStore
    from app.tool_execution_service import ToolExecutionEngineService

    db = database()
    resolver = D1WebQuoteWriteScopeResolver(D1(db))
    scope = await resolver(SEL)
    binding = build_web_quote_write_tool_binding(resolver)
    engine = ToolExecutionEngineService(
        tool_binding_resolver=lambda app: binding if app == APP_ID else None,
        approval_decision_verifier=AuthenticatedFirstPartyApprovalDecisionVerifier(),
        continuation_store=InMemoryContinuationStore(),
    )
    started = await engine.execute_payload({
        "app_id": APP_ID, "agent_id": AGENT_ID,
        "tool_id": CANONICAL_TOOL, "arguments": quote_write_arguments(scope),
    })
    assert started.status_code == 202, started.body
    assert started.body["tool"]["status"] == "paused"
    continuation_ref = started.body["tool"]["continuation_ref"]
    record = engine._continuation_store.resolve(
        app_id=APP_ID, continuation_ref=continuation_ref)
    submission = {
        "decision_id": "decision_hark_write_test",
        "pause_id": record.pause.pause_id,
        "outcome": "approved",
        "authority_ref": "first_party_owner",
        "evidence_ref": "first_party_session",
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }
    resumed = await engine.resume_payload({
        "app_id": APP_ID, "continuation_ref": continuation_ref,
        "decision": submission,
    })
    assert resumed.status_code == 403, resumed.body
    assert resumed.body["error"]["code"] == "web_xlsx_write_grant_unavailable"
    assert db.execute(
        "SELECT state FROM claw_web_xlsx_quote_edit_receipts "
        "WHERE selection_ref=?", (SEL,)
    ).fetchone()["state"] == "dispatching"
    # The untrusted, in-memory continuation may NEVER be provisioned with a
    # privileged callback as a replacement for real durable owner proof.
    with pytest.raises(ValueError):
        ToolExecutionEngineService(
            tool_binding_resolver=lambda app: binding if app == APP_ID else None,
            approval_decision_verifier=AuthenticatedFirstPartyApprovalDecisionVerifier(),
            continuation_store=InMemoryContinuationStore(),
            web_quote_write_approval_grant=lambda **_: True,
        )
    db.close()
