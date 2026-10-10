"""Core/Engine user approval for web XLSX original intent."""
from datetime import datetime, timezone

import pytest
from padiem_ai_core import ToolInvocation, ToolRuntimeError
from padiem_ai_core.agent_approval import tool_invocation_digest
from app.approval_verifier import AuthenticatedFirstPartyApprovalDecisionVerifier
from app.orchestration_continuation import InMemoryContinuationStore
from app.orchestration_service import OrchestrationEngineService
from app.web_xlsx_p01_tool_binding import (
    APP_ID, AGENT_ID, SCOPE, RUNTIME_TOOL, CANONICAL_TOOL,
    TrustedWebXlsxSelectionScope, build_web_xlsx_p01_tool_binding,
    with_web_xlsx_p01_tool_binding, web_xlsx_p01_arguments,
)

SOURCE = TrustedWebXlsxSelectionScope(
    owner_id="owner_web_a", workspace_id="owner:web_a",
    run_id="run_web_3580_a", selection_ref="sel_" + "a"*32,
    document_id="doc_" + "b"*32, source_sha256="c"*64,
    original_immutable=True, source_active=True,
)


def arguments():
    return {
        "owner_id": SOURCE.owner_id,
        "workspace_id": SOURCE.workspace_id,
        "run_id": SOURCE.run_id,
        "selection_ref": SOURCE.selection_ref,
        "document_id": SOURCE.document_id,
        "source_sha256": SOURCE.source_sha256,
        "operation": "read_for_workcopy", "source_kind": "browser_upload",
        "original_immutable": True, "read_content": False,
        "drive_write": False, "local_pc_access": False,
    }


def make_binding():
    called = []
    async def lookup(ref):
        called.append(ref)
        return SOURCE if ref == SOURCE.selection_ref else None
    return build_web_xlsx_p01_tool_binding(lookup), called


def input_payload(binding):
    profile = binding.resolve_authority(AGENT_ID).compiled.runtime_profile
    return {
        "app_id": APP_ID,
        "agent": {
            "id": profile.id, "title": profile.title,
            "description": profile.description,
            "system_instruction": profile.system_instruction,
            "task_type": profile.task_type, "optimize_for": profile.optimize_for,
            "max_tokens": profile.max_tokens,
            "model_policy": {"model": "test/none"},
        },
        "messages": [{"role": "user", "content": "Confirm selected web XLSX"}],
        "trace_id": "trace_3580_web_original",
        "execution_context": {
            "trace_id": "trace_3580_web_original", "timeout_seconds": 5.0,
        },
        "agent_plan": {"agent_id": AGENT_ID, "steps": [{
            "step_id": "step_1", "objective": "Confirm original",
            "tool_id": RUNTIME_TOOL,
        }]},
        "tool_arguments": {"step_1": arguments()},
        "subject_id": "subject:padiem-web-a",
        "require_evidence": False, "require_verification": False,
    }


class NoProvider:
    async def run(self, request):
        raise AssertionError("No model provider needed")


def engine(binding):
    ledger = InMemoryContinuationStore()
    service = OrchestrationEngineService(
        runtime_factory=lambda _: NoProvider(), b14_service_bound=True,
        continuation_store=ledger,
        approval_decision_verifier=AuthenticatedFirstPartyApprovalDecisionVerifier(),
        tool_binding_resolver=lambda app: binding if app == APP_ID else None,
    )
    return service, ledger

def test_web_confirmation_requires_real_trusted_host_registration():
    existing = lambda app: None
    assert with_web_xlsx_p01_tool_binding(existing) is existing
    assert with_web_xlsx_p01_tool_binding(existing, enabled=True) is existing
    assert with_web_xlsx_p01_tool_binding(
        existing, selection_resolver=lambda _: SOURCE,
    ) is existing
    registered = with_web_xlsx_p01_tool_binding(
        existing, enabled=True, selection_resolver=lambda _: SOURCE,
    )
    assert registered(APP_ID).registry.canonical_tool_ids == (CANONICAL_TOOL,)
    assert registered("other") is None


@pytest.mark.asyncio
async def test_actual_toolruntime_pause_and_engine_verified_resume():
    binding, called = make_binding()
    auth = binding.resolve_authority(AGENT_ID)
    invocation = ToolInvocation(tool_id=RUNTIME_TOOL, arguments=arguments())
    with pytest.raises(ToolRuntimeError) as blocked:
        await binding.tool_runtime.execute(
            invocation, auth.compiled.runtime_profile, auth.authorization,
        )
    assert blocked.value.code == "tool_user_confirmation_required"
    assert called == []
    service, ledger = engine(binding)
    initial = input_payload(binding)
    response = await service.orchestrate_payload(initial)
    assert response.status_code == 200, response.body
    result = response.body["orchestration"]
    assert result["execution"]["metadata"]["status"] == "paused"
    assert called == []
    ref = result["continuation_ref"]
    record = ledger.resolve(app_id=APP_ID, continuation_ref=ref)
    assert record.pause.invocation_sha256 == tool_invocation_digest(invocation)
    assert record.pause.approval_scope == (SCOPE,)
    submission = {
        "decision_id": "decision_web_confirm_a",
        "pause_id": record.pause.pause_id, "outcome": "approved",
        "authority_ref": "first_party_owner",
        "evidence_ref": "first_party_session",
        "decided_at": min(datetime.now(timezone.utc),
                          record.pause.expires_at).isoformat(),
    }
    resume = {k: v for k, v in initial.items()
              if k not in {"require_evidence", "require_verification"}}
    resume.update({"continuation_ref": ref, "decision": submission})
    accepted = await service.resume_payload(resume)
    assert accepted.status_code == 200, accepted.body
    assert accepted.body["orchestration"]["execution"]["metadata"]["status"] == "completed"
    assert called == [SOURCE.selection_ref]
    rejected_replay = await service.resume_payload(resume)
    assert rejected_replay.status_code != 200
    assert called == [SOURCE.selection_ref]


@pytest.mark.asyncio
async def test_denied_engine_decision_does_not_reach_handler():
    binding, called = make_binding()
    service, ledger = engine(binding)
    initial = input_payload(binding)
    paused = await service.orchestrate_payload(initial)
    ref = paused.body["orchestration"]["continuation_ref"]
    record = ledger.resolve(app_id=APP_ID, continuation_ref=ref)
    resume = {k: v for k, v in initial.items()
              if k not in {"require_evidence", "require_verification"}}
    resume.update({
        "continuation_ref": ref,
        "decision": {
            "decision_id": "decision_web_denied",
            "pause_id": record.pause.pause_id,
            "outcome": "denied",
            "authority_ref": "first_party_owner",
            "evidence_ref": "first_party_session",
            "decided_at": datetime.now(timezone.utc).isoformat(),
        },
    })
    denied = await service.resume_payload(resume)
    assert denied.status_code != 200
    assert called == []

@pytest.mark.asyncio
async def test_confirmed_selection_still_denies_wrong_sha_and_foreign_owner():
    from padiem_ai_core import ToolAuthorizationContext
    binding, calls = make_binding()
    authority = binding.resolve_authority(AGENT_ID)
    approved_context = ToolAuthorizationContext(
        app_id=APP_ID, agent_id=authority.compiled.runtime_profile.id,
        granted_auth_scopes=(SCOPE,), user_confirmed_tools=(RUNTIME_TOOL,),
    )
    for field, invalid in (
        ("owner_id", "owner_web_foreign"),
        ("workspace_id", "owner:web_foreign"),
        ("run_id", "run_other"),
        ("document_id", "doc_" + "d"*32),
        ("source_sha256", "f"*64),
        ("selection_ref", "sel_" + "e"*32),
    ):
        args = {**arguments(), field: invalid}
        with pytest.raises(ToolRuntimeError) as exc:
            await binding.tool_runtime.execute(
                ToolInvocation(tool_id=RUNTIME_TOOL, arguments=args),
                authority.compiled.runtime_profile, approved_context,
            )
        assert exc.value.code == "tool_execution_failed"
    assert calls


@pytest.mark.asyncio
async def test_core_refuses_unsafe_extra_fields_and_missing_original_confirmation():
    from padiem_ai_core import ToolAuthorizationContext
    binding, _ = make_binding()
    authority = binding.resolve_authority(AGENT_ID)
    approved_context = ToolAuthorizationContext(
        app_id=APP_ID, agent_id=authority.compiled.runtime_profile.id,
        granted_auth_scopes=(SCOPE,), user_confirmed_tools=(RUNTIME_TOOL,),
    )
    for replacement in (
        {"read_content": True}, {"drive_write": True},
        {"local_pc_access": True}, {"original_immutable": False},
        {"operation": "delete"}, {"source_kind": "local_pc"},
        {"path": "C:/workbook.xlsx"},
    ):
        with pytest.raises(ToolRuntimeError) as exc:
            await binding.tool_runtime.execute(
                ToolInvocation(tool_id=RUNTIME_TOOL,
                               arguments={**arguments(), **replacement}),
                authority.compiled.runtime_profile, approved_context,
            )
        assert exc.value.code == "invalid_tool_arguments"

def test_server_only_arguments_builder_matches_exact_invocation():
    assert web_xlsx_p01_arguments(SOURCE) == arguments()
    with pytest.raises(ValueError):
        web_xlsx_p01_arguments(None)
    from dataclasses import replace
    with pytest.raises(ValueError):
        web_xlsx_p01_arguments(replace(SOURCE, source_active=False))
