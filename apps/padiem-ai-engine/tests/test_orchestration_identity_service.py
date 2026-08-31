"""Integration tests for identity-bound orchestration resume wiring."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from padiem_ai_core import (
    ApprovalOutcome,
    ApprovalPause,
    ApprovalRequirement,
    B14RouteMetadata,
    ExecutionContext,
    ExecutionRequest,
    ExecutionResult,
    RunMetadata,
    RunStatus,
    VerifiedApprovalDecision,
)

from app.continuation_binding import InMemoryIdentityBoundContinuationStore
from app.continuation_identity import build_continuation_execution_identity
from app.orchestration_identity_service import IdentityBoundOrchestrationEngineService
from app.service import build_execution_request


class MockRuntime:
    def __init__(self) -> None:
        self.call_count = 0

    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        self.call_count += 1
        return ExecutionResult(
            answer="resumed",
            route=B14RouteMetadata(selected_provider="mock", selected_model="mock"),
            metadata=RunMetadata(
                trace_id=request.trace_id or "tr_identity",
                app_id="b62",
                agent_id=request.agent.id,
                status=RunStatus.COMPLETED,
            ),
        )


class Verifier:
    def verify(self, submission, *, pause, app_id):
        return VerifiedApprovalDecision(
            decision_id=submission.decision_id,
            pause_id=submission.pause_id,
            outcome=submission.outcome,
            authority_ref=submission.authority_ref,
            evidence_ref=submission.evidence_ref,
            decided_at=submission.decided_at,
        )


def payload() -> dict:
    return {
        "app_id": "b62",
        "agent": {
            "id": "agent:padiem:orchestrator_1",
            "title": "Orchestrator",
            "description": "Orchestrates execution",
            "system_instruction": "Execute tasks",
            "task_type": "general",
            "optimize_for": "balanced",
            "max_tokens": 2048,
        },
        "messages": [{"role": "user", "content": "Hello engine"}],
        "session_id": "session_identity",
        "additional_system_context": "Bound context",
        "trace_id": "tr_identity",
        "execution_context": {
            "trace_id": "tr_identity",
            "timeout_seconds": 15.0,
        },
        "subject_id": "subject_identity",
        "max_retries": 3,
        "require_evidence": False,
        "require_verification": False,
    }


def pause() -> ApprovalPause:
    now = datetime.now(timezone.utc)
    return ApprovalPause(
        pause_id="pause_identity",
        run_id="run_identity",
        agent_runtime_id="agent:padiem:orchestrator_1",
        tool_id="calc",
        invocation_sha256="0" * 64,
        requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=1,
        created_at=now,
        expires_at=now + timedelta(minutes=10),
        trace_id="tr_identity",
    )


def decision() -> dict:
    return {
        "decision_id": "decision_identity",
        "pause_id": "pause_identity",
        "outcome": ApprovalOutcome.APPROVED.value,
        "authority_ref": "user:admin",
        "evidence_ref": "session:auth",
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }


def issue(store: InMemoryIdentityBoundContinuationStore, original: dict) -> str:
    _, request, context = build_execution_request(
        {
            key: original[key]
            for key in (
                "app_id", "agent", "messages", "session_id",
                "additional_system_context", "trace_id", "execution_context",
            )
            if key in original
        }
    )
    assert context is not None
    identity = build_continuation_execution_identity(
        app_id=original["app_id"],
        request=request,
        context=context,
        subject_id=original.get("subject_id"),
        plan=None,
        recovery_policy=None,
        max_retries=original.get("max_retries", 3),
        require_evidence=original.get("require_evidence", False),
        require_verification=original.get("require_verification", False),
    )
    return store.issue(
        app_id=original["app_id"],
        pause=pause(),
        execution_identity=identity,
    )


async def test_exact_identity_resume_executes_once_and_consumes() -> None:
    runtime = MockRuntime()
    store = InMemoryIdentityBoundContinuationStore()
    original = payload()
    ref = issue(store, original)
    service = IdentityBoundOrchestrationEngineService(
        runtime_factory=lambda app_id: runtime,
        b14_service_bound=True,
        approval_decision_verifier=Verifier(),
        continuation_store=store,
    )
    request = dict(original)
    request["continuation_ref"] = ref
    request["decision"] = decision()
    response = await service.resume_payload(request)
    assert response.status_code == 200
    assert runtime.call_count == 1
    try:
        store.resolve(app_id="b62", continuation_ref=ref)
    except Exception as exc:
        assert getattr(exc, "code", None) == "continuation_consumed"
    else:
        raise AssertionError("successful resume must consume continuation")


async def test_message_mutation_rejected_before_claim_and_core_execution() -> None:
    runtime = MockRuntime()
    store = InMemoryIdentityBoundContinuationStore()
    original = payload()
    ref = issue(store, original)
    service = IdentityBoundOrchestrationEngineService(
        runtime_factory=lambda app_id: runtime,
        b14_service_bound=True,
        approval_decision_verifier=Verifier(),
        continuation_store=store,
    )
    request = dict(original)
    request["messages"] = [{"role": "user", "content": "Changed"}]
    request["continuation_ref"] = ref
    request["decision"] = decision()
    response = await service.resume_payload(request)
    assert response.status_code == 409
    assert response.body["error"]["code"] == "continuation_identity_mismatch"
    assert runtime.call_count == 0
    record = store.resolve(app_id="b62", continuation_ref=ref)
    assert record.state == "active"
    assert record.claim_token is None


async def test_subject_and_policy_mutation_rejected_before_claim() -> None:
    runtime = MockRuntime()
    store = InMemoryIdentityBoundContinuationStore()
    original = payload()
    ref = issue(store, original)
    service = IdentityBoundOrchestrationEngineService(
        runtime_factory=lambda app_id: runtime,
        b14_service_bound=True,
        approval_decision_verifier=Verifier(),
        continuation_store=store,
    )
    request = dict(original)
    request["subject_id"] = "other_subject"
    request["max_retries"] = 4
    request["continuation_ref"] = ref
    request["decision"] = decision()
    response = await service.resume_payload(request)
    assert response.status_code == 409
    assert response.body["error"]["code"] == "continuation_identity_mismatch"
    assert runtime.call_count == 0
    record = store.resolve(app_id="b62", continuation_ref=ref)
    assert record.state == "active"
    assert record.claim_token is None


async def test_unknown_resume_field_fails_closed_without_claim() -> None:
    runtime = MockRuntime()
    store = InMemoryIdentityBoundContinuationStore()
    original = payload()
    ref = issue(store, original)
    service = IdentityBoundOrchestrationEngineService(
        runtime_factory=lambda app_id: runtime,
        b14_service_bound=True,
        approval_decision_verifier=Verifier(),
        continuation_store=store,
    )
    request = dict(original)
    request["continuation_ref"] = ref
    request["decision"] = decision()
    request["future_execution_authority"] = {"allow": True}
    response = await service.resume_payload(request)
    assert response.status_code == 400
    assert response.body["error"]["code"] == "unsupported_orchestration_field"
    assert runtime.call_count == 0
    record = store.resolve(app_id="b62", continuation_ref=ref)
    assert record.state == "active"
    assert record.claim_token is None
