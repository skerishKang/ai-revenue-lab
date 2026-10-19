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
async def test_real_engine_confirmation_pause_then_first_party_approved_decision(listing):
    binding = build_hark_office_p01_tool_binding()
    authority = binding.resolve_authority(AGENT_ID)
    tool = LIST_TOOL_ID if listing else READ_TOOL_ID
    invocation = ToolInvocation(tool_id=tool, arguments=_args(listing=listing))
    with pytest.raises(ToolRuntimeError) as blocked:
        await binding.tool_runtime.execute(
            invocation, authority.compiled.runtime_profile, authority.authorization,
        )
    assert blocked.value.code == "tool_user_confirmation_required"
    assert not authority.authorization.user_confirmed_tools

    service, store = _engine(binding)
    payload = _payload(binding, listing=listing)
    paused = await service.orchestrate_payload(payload)
    assert paused.status_code == 200, paused.body
    outcome = paused.body["orchestration"]
    assert outcome["execution"]["metadata"]["status"] == "paused"
    stored = store.resolve(app_id=APP_ID, continuation_ref=outcome["continuation_ref"])
    assert stored.pause.tool_id == tool
    assert stored.pause.approval_scope == (FILE_SCOPE,)
    assert stored.pause.invocation_sha256 == __import__(
        "padiem_ai_core.agent_approval", fromlist=["tool_invocation_digest"]
    ).tool_invocation_digest(invocation)

    decision = {
        "decision_id": "decision_3580_" + ("list" if listing else "read"),
        "pause_id": stored.pause.pause_id,
        "outcome": "approved", "authority_ref": "owner_3580_first_party",
        "evidence_ref": "session_3580_first_party",
        "decided_at": min(datetime.now(timezone.utc),
                          stored.pause.expires_at).isoformat(),
    }
    resumed = {k: v for k, v in payload.items()
               if k not in {"require_evidence", "require_verification"}}
    resumed["continuation_ref"] = outcome["continuation_ref"]
    resumed["decision"] = decision
    result = await service.resume_payload(resumed)
    assert result.status_code == 200, result.body
    assert result.body["orchestration"]["execution"]["metadata"]["status"] == "completed"
    assert not result.body["orchestration"].get("local_bytes")
    with pytest.raises(Exception):
        store.resolve(app_id=APP_ID, continuation_ref=outcome["continuation_ref"])


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
    confirmed = ToolAuthorizationContext(
        app_id=APP_ID, agent_id=authority.compiled.runtime_profile.id,
        granted_auth_scopes=(FILE_SCOPE,),
        user_confirmed_tools=(READ_TOOL_ID,),
    )
    with pytest.raises(ToolRuntimeError) as invalid:
        await binding.tool_runtime.execute(
            ToolInvocation(tool_id=READ_TOOL_ID, arguments=args),
            authority.compiled.runtime_profile, confirmed,
        )
    assert invalid.value.code == "invalid_tool_arguments"
    for unsafe in ("../private.xlsx", "C:/secret.xlsx", "nested/other.xlsx"):
        invalid_path = _args(listing=False)
        invalid_path["path_relative"] = unsafe
        with pytest.raises(ToolRuntimeError) as exc:
            await binding.tool_runtime.execute(
                ToolInvocation(tool_id=READ_TOOL_ID, arguments=invalid_path),
                authority.compiled.runtime_profile, confirmed,
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


async def _actual_approved_office_resume(*, listing, sink, outcome="approved"):
    binding = build_hark_office_p01_tool_binding()
    engine, store = _engine(binding, receipt_sink=sink)
    payload = _payload(binding, listing=listing)
    paused = await engine.orchestrate_payload(
        payload, trusted_office_run_id=payload["tool_arguments"]["step_1"]["run_id"],
    )
    assert paused.status_code == 200, paused.body
    continuation_ref = paused.body["orchestration"]["continuation_ref"]
    record = store.resolve(app_id=APP_ID, continuation_ref=continuation_ref)
    submission = {
        "decision_id": "decision_hark_receipt_" + ("list" if listing else "read"),
        "pause_id": record.pause.pause_id,
        "outcome": outcome,
        "authority_ref": "trusted_user_session",
        "evidence_ref": "first_party_verified_session",
        "decided_at": min(datetime.now(timezone.utc), record.pause.expires_at).isoformat(),
    }
    resumed = {
        k: v for k, v in payload.items()
        if k not in {"require_evidence", "require_verification"}
    }
    resumed["continuation_ref"] = continuation_ref
    resumed["decision"] = submission
    result = await engine.resume_payload(resumed)
    return result, engine, store, resumed, continuation_ref


@pytest.mark.asyncio
async def test_only_actually_verified_consumed_read_emits_private_office_receipt():
    sink = _VerifiedReceiptSink()
    result, engine, store, replay, ref = await _actual_approved_office_resume(
        listing=False, sink=sink,
    )
    assert result.status_code == 200, result.body
    assert len(sink.receipts) == 1
    receipt = sink.receipts[0]
    assert receipt.pause.run_id == _args(listing=False)["run_id"]
    assert receipt.request_fingerprint == "b" * 64
    assert receipt.verified_decision.outcome.value == "approved"
    assert receipt.continuation_ref == ref
    assert receipt.safe_dict()["device_permission_granted"] is False
    assert receipt.safe_dict()["resident_dispatched"] is False
    assert "verified_decision" not in str(result.body)
    assert "first_party_verified_session" not in str(result.body)
    replayed = await engine.resume_payload(replay)
    assert replayed.status_code != 200
    assert len(sink.receipts) == 1


@pytest.mark.asyncio
async def test_list_approval_never_becomes_selected_file_read_receipt():
    sink = _VerifiedReceiptSink()
    outcome, *_ = await _actual_approved_office_resume(listing=True, sink=sink)
    assert outcome.status_code == 200
    assert sink.receipts == []


@pytest.mark.asyncio
async def test_denied_office_read_never_emits_receipt():
    sink = _VerifiedReceiptSink()
    outcome, *_ = await _actual_approved_office_resume(
        listing=False, sink=sink, outcome="denied",
    )
    assert outcome.status_code != 200
    assert sink.receipts == []


@pytest.mark.asyncio
async def test_failed_private_receipt_storage_fail_closed_after_consumed():
    sink = _VerifiedReceiptSink(persist=False)
    outcome, engine, store, replay, ref = await _actual_approved_office_resume(
        listing=False, sink=sink,
    )
    assert outcome.status_code == 503
    assert outcome.body["error"]["code"] == "office_approval_receipt_unavailable"
    assert len(sink.receipts) == 1
    another = await engine.resume_payload(replay)
    assert another.status_code != 200
    assert len(sink.receipts) == 1


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
    assert result.body["orchestration"]["execution"]["metadata"]["status"] == "paused"
    record = store.resolve(
        app_id=APP_ID,
        continuation_ref=result.body["orchestration"]["continuation_ref"],
    )
    assert record.pause.run_id.startswith("bridge_run_")
