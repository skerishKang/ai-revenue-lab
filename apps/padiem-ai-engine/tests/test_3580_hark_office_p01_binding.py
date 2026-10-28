"""Actual Core ToolRuntime and Engine first-party P01 Office tool confirmations."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from padiem_ai_core import ToolInvocation, ToolRuntimeError
from app.hark_office_p01_tool_binding import (
    AGENT_ID, APP_ID, FILE_SCOPE, LIST_CANONICAL_ID, READ_CANONICAL_ID,
    LIST_TOOL_ID, READ_TOOL_ID,
    build_hark_office_p01_tool_binding, with_hark_office_p01_tool_binding,
)
from app.approval_verifier import AuthenticatedFirstPartyApprovalDecisionVerifier
from app.orchestration_continuation import InMemoryContinuationStore
from app.orchestration_service import OrchestrationEngineService


def _args(*, listing: bool) -> dict:
    common = {
        "action_id": "act_3580_real_engine_p01",
        "run_id": "run_3580_actual_file", "device_id": "device_3580",
        "root_ref": "quote_root_3580",
        "request_fingerprint": "b"*64,
    }
    if listing:
        return {**common, "max_candidates": 10, "name_contains": "견적서",
                "metadata_only": True, "recursive": False,
                "read_content": False, "file_extensions": ["xls", "xlsx"],
                "whole_pc_scan": False}
    return {**common, "operation": "read",
            "path_relative": "original_quote.xlsx",
            "requested_at": "2026-10-10T12:00:00+00:00",
            "content_bytes": 0, "content_sha256": None,
            "directory_enumeration": False, "recursive_delete": False,
            "admin_elevation": False}


class _NeverProvider:
    async def run(self, _request):
        raise AssertionError("provider cannot run during deterministic P01 approval")


def _engine(binding, *, receipt_sink=None):
    store = InMemoryContinuationStore()
    service = OrchestrationEngineService(
        runtime_factory=lambda _: _NeverProvider(),
        b14_service_bound=True, continuation_store=store,
        approval_decision_verifier=AuthenticatedFirstPartyApprovalDecisionVerifier(),
        tool_binding_resolver=lambda app_id: binding if app_id == APP_ID else None,
        approved_office_read_sink=receipt_sink,
    )
    return service, store


def _payload(binding, *, listing):
    authority = binding.resolve_authority(AGENT_ID)
    p = authority.compiled.runtime_profile
    tool = LIST_TOOL_ID if listing else READ_TOOL_ID
    return {
        "app_id": APP_ID,
        "agent": {
            "id": p.id, "title": p.title, "description": p.description,
            "system_instruction": p.system_instruction,
            "task_type": p.task_type, "optimize_for": p.optimize_for,
            "max_tokens": p.max_tokens, "model_policy": {"model": "test/none"},
        },
        "messages": [{"role": "user", "content": "Confirm the selected Office intent"}],
        "trace_id": "trace_3580_real_office",
        "execution_context": {"trace_id": "trace_3580_real_office", "timeout_seconds": 5.0},
        "agent_plan": {"agent_id": AGENT_ID, "steps": [{
            "step_id": "step_1", "objective": "User confirmation of bounded Office intent",
            "tool_id": tool,
        }]},
        "tool_arguments": {"step_1": _args(listing=listing)},
        "subject_id": "subject:padiem-office",
        "require_evidence": False, "require_verification": False,
    }


def test_production_disabled_does_not_wrap_or_weaken_existing_resolver():
    base = lambda _id: None
    assert with_hark_office_p01_tool_binding({}, base) is base
    assert with_hark_office_p01_tool_binding(
        type("E", (), {"PADIEM_ENGINE_HARK_OFFICE_P01_ENABLED": "0"})(), base
    ) is base


def test_explicit_deployment_only_registration_matches_canonical_tools():
    base = lambda app_id: None
    enabled = type("E", (), {"PADIEM_ENGINE_HARK_OFFICE_P01_ENABLED": "1"})()
    resolver = with_hark_office_p01_tool_binding(enabled, base)
    assert resolver is not base
    binding = resolver(APP_ID)
    assert binding.registry.canonical_tool_ids == (
        LIST_CANONICAL_ID, READ_CANONICAL_ID,
    )
    assert resolver("foreign_app") is None
    assert binding.resolve_authority(AGENT_ID).authorization.granted_auth_scopes == (FILE_SCOPE,)


@pytest.mark.asyncio
@pytest.mark.parametrize("listing", [True, False])
async def test_a_connected_owner_reaches_the_office_handler_without_a_pause(listing):
    """Owner decision 2026-10-28: pre-delegated — the handler runs directly."""
    binding = build_hark_office_p01_tool_binding()
    authority = binding.resolve_authority(AGENT_ID)
    tool = LIST_TOOL_ID if listing else READ_TOOL_ID
    invocation = ToolInvocation(tool_id=tool, arguments=_args(listing=listing))
    await binding.tool_runtime.execute(
        invocation, authority.compiled.runtime_profile, authority.authorization,
    )
    service, store = _engine(binding)
    payload = _payload(binding, listing=listing)
    outcome = await service.orchestrate_payload(payload)
    assert outcome.status_code == 200, outcome.body
    result = outcome.body["orchestration"]
    assert result["execution"]["metadata"]["status"] == "completed"
    assert "continuation_ref" not in result


@pytest.mark.asyncio
async def test_toolruntime_denies_cross_scope_and_forbidden_extra_arguments():
    binding = build_hark_office_p01_tool_binding()
    authority = binding.resolve_authority(AGENT_ID)
    invocation = ToolInvocation(tool_id=READ_TOOL_ID, arguments=_args(listing=False))
    from padiem_ai_core import ToolAuthorizationContext
    unauthorized = ToolAuthorizationContext(
        app_id=APP_ID, agent_id=authority.compiled.runtime_profile.id,
        granted_auth_scopes=(),
    )
    with pytest.raises(ToolRuntimeError) as missing_scope:
        await binding.tool_runtime.execute(
            invocation, authority.compiled.runtime_profile, unauthorized,
        )
    assert missing_scope.value.code == "tool_auth_scope_missing"

    args = _args(listing=False)
    args["drive_upload_allowed"] = True
    with pytest.raises(ToolRuntimeError) as invalid:
        await binding.tool_runtime.execute(
            ToolInvocation(tool_id=READ_TOOL_ID, arguments=args),
            authority.compiled.runtime_profile, authority.authorization,
        )
    assert invalid.value.code == "invalid_tool_arguments"
    for unsafe in ("../private.xlsx", "C:/secret.xlsx", "nested/other.xlsx"):
        invalid_path = _args(listing=False)
        invalid_path["path_relative"] = unsafe
        with pytest.raises(ToolRuntimeError) as exc:
            await binding.tool_runtime.execute(
                ToolInvocation(tool_id=READ_TOOL_ID, arguments=invalid_path),
                authority.compiled.runtime_profile, authority.authorization,
            )
        assert exc.value.code == "invalid_tool_arguments"


class _VerifiedReceiptSink:
    def __init__(self, *, persist=True):
        self.persist = persist
        self.receipts = []

    async def record_verified_office_read(self, receipt):
        from app.hark_office_p01_receipt import ApprovedOfficeReadReceipt
        assert isinstance(receipt, ApprovedOfficeReadReceipt)
        self.receipts.append(receipt)
        return self.persist


@pytest.mark.asyncio
async def test_office_read_and_listing_run_directly_without_fabricating_a_receipt():
    """With no pause there is no approved decision, so no receipt is invented."""
    sink = _VerifiedReceiptSink()
    binding = build_hark_office_p01_tool_binding()
    engine, store = _engine(binding, receipt_sink=sink)
    for listing in (False, True):
        payload = _payload(binding, listing=listing)
        result = await engine.orchestrate_payload(
            payload, trusted_office_run_id=payload["tool_arguments"]["step_1"]["run_id"],
        )
        assert result.status_code == 200, result.body
        assert result.body["orchestration"]["execution"]["metadata"]["status"] == "completed"
        assert "continuation_ref" not in result.body["orchestration"]
    assert sink.receipts == []


def test_approved_receipt_is_immutable_and_exact_digest_only():
    from dataclasses import replace
    from datetime import timedelta
    from app.hark_office_p01_receipt import ApprovedOfficeReadReceipt
    from padiem_ai_core.agent_approval import (
        ApprovalOutcome, ApprovalPause, ApprovalRequirement,
        VerifiedApprovalDecision, tool_invocation_digest,
    )
    now = datetime.now(timezone.utc)
    args = _args(listing=False)
    pause = ApprovalPause(
        pause_id="pause_receipt_3580", run_id=args["run_id"],
        agent_runtime_id="agent_receipt_3580", tool_id=READ_TOOL_ID,
        invocation_sha256=tool_invocation_digest(
            ToolInvocation(tool_id=READ_TOOL_ID, arguments=args)
        ),
        requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=1, created_at=now - timedelta(minutes=3),
        expires_at=now + timedelta(minutes=3),
        approval_scope=(FILE_SCOPE,),
    )
    decision = VerifiedApprovalDecision(
        decision_id="dec_receipt_3580",
        pause_id=pause.pause_id,
        outcome=ApprovalOutcome.APPROVED,
        authority_ref="trusted_engine",
        evidence_ref="first_party_verified",
        decided_at=now,
    )
    receipt = ApprovedOfficeReadReceipt(
        app_id=APP_ID, continuation_ref="cont_real_receipt_3580",
        pause=pause, verified_decision=decision,
        exact_tool_arguments=tuple(sorted(args.items())),
    )
    assert receipt.pause.invocation_sha256 == pause.invocation_sha256
    for mutation in (
        {"path_relative": "another.xlsx"},
        {"run_id": "foreign_user_run"},
        {"request_fingerprint": "c"*64},
        {"path_relative": "../secrets.xlsx"},
        {"directory_enumeration": True},
    ):
        tampered = {**args, **mutation}
        with pytest.raises(ValueError):
            replace(receipt, exact_tool_arguments=tuple(sorted(tampered.items())))
    with pytest.raises(ValueError):
        replace(receipt, verified_decision=replace(
            decision, outcome=ApprovalOutcome.DENIED,
        ))

@pytest.mark.asyncio
async def test_trusted_engine_office_run_requires_exact_registered_request_identity():
    binding = build_hark_office_p01_tool_binding()
    engine, store = _engine(binding, receipt_sink=_VerifiedReceiptSink())
    request = _payload(binding, listing=False)
    foreign = await engine.orchestrate_payload(
        request, trusted_office_run_id="run_other_owner",
    )
    assert foreign.status_code == 409
    assert foreign.body["error"]["code"] == "office_run_identity_mismatch"
    wrong_shape = await engine.orchestrate_payload(
        request, trusted_office_run_id="../outside",
    )
    assert wrong_shape.status_code == 409
    # Public JSON cannot smuggle the keyword into the private call.
    request["trusted_office_run_id"] = _args(listing=False)["run_id"]
    denied = await engine.orchestrate_payload(request)
    assert denied.status_code == 400
    assert denied.body["error"]["code"] == "invalid_request"


@pytest.mark.asyncio
async def test_unconfigured_sink_does_not_export_any_private_approval():
    binding = build_hark_office_p01_tool_binding()
    engine, store = _engine(binding)
    payload = _payload(binding, listing=False)
    result = await engine.orchestrate_payload(payload)
    assert result.status_code == 200
    assert result.body["orchestration"]["execution"]["metadata"]["status"] == "completed"
    assert "continuation_ref" not in result.body["orchestration"]
    assert "bridge_run_" not in str(result.body)
