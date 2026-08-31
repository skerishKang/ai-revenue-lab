"""Race coverage for orchestration continuation cancel/resume semantics."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from padiem_ai_core import (
    ApprovalPause,
    ApprovalRequirement,
    B14RouteMetadata,
    ExecutionRequest,
    ExecutionResult,
    RunMetadata,
    RunStatus,
    VerifiedApprovalDecision,
)

from app.orchestration_service import InMemoryContinuationStore, OrchestrationEngineService


class BlockingRuntime:
    def __init__(self) -> None:
        self.call_count = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        self.call_count += 1
        self.started.set()
        await self.release.wait()
        return ExecutionResult(
            answer="resumed",
            route=B14RouteMetadata(selected_provider="mock_provider", selected_model="mock_model"),
            metadata=RunMetadata(
                trace_id=request.trace_id or "tr_race",
                app_id="b62",
                agent_id=request.agent.id,
                status=RunStatus.COMPLETED,
            ),
        )


class ImmediateRuntime:
    def __init__(self) -> None:
        self.call_count = 0

    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        self.call_count += 1
        return ExecutionResult(
            answer="resumed",
            route=B14RouteMetadata(selected_provider="mock_provider", selected_model="mock_model"),
            metadata=RunMetadata(
                trace_id=request.trace_id or "tr_race",
                app_id="b62",
                agent_id=request.agent.id,
                status=RunStatus.COMPLETED,
            ),
        )


class TrustedVerifier:
    def verify(self, submission, *, pause, app_id):
        return VerifiedApprovalDecision(
            decision_id=submission.decision_id,
            pause_id=submission.pause_id,
            outcome=submission.outcome,
            authority_ref=submission.authority_ref,
            evidence_ref=submission.evidence_ref,
            decided_at=submission.decided_at,
        )


def _pause() -> ApprovalPause:
    now = datetime.now(timezone.utc)
    return ApprovalPause(
        pause_id="pause_race_1",
        run_id="run_race_1",
        agent_runtime_id="agent:padiem:orchestrator_1",
        tool_id="calc",
        invocation_sha256="0" * 64,
        requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=1,
        created_at=now,
        expires_at=now + timedelta(minutes=10),
        trace_id="tr_race",
    )


def _payload(ref: str) -> dict:
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
        "messages": [{"role": "user", "content": "resume"}],
        "trace_id": "tr_race",
        "execution_context": {"trace_id": "tr_race", "timeout_seconds": 15.0},
        "continuation_ref": ref,
        "decision": {
            "decision_id": "decision_race_1",
            "pause_id": "pause_race_1",
            "outcome": "approved",
            "authority_ref": "user:admin",
            "evidence_ref": "session:auth",
            "decided_at": datetime.now(timezone.utc).isoformat(),
        },
    }


def _service(runtime):
    store = InMemoryContinuationStore()
    service = OrchestrationEngineService(
        runtime_factory=lambda app_id: runtime,
        b14_service_bound=True,
        approval_decision_verifier=TrustedVerifier(),
        continuation_store=store,
    )
    ref = store.issue(app_id="b62", pause=_pause(), plan_id=None)
    return service, store, ref


async def test_resume_claims_first_cancel_is_rejected_and_core_executes_once() -> None:
    runtime = BlockingRuntime()
    service, store, ref = _service(runtime)

    resume_task = asyncio.create_task(service.resume_payload(_payload(ref)))
    await asyncio.wait_for(runtime.started.wait(), timeout=1.0)

    cancel = await service.cancel_payload(
        {"app_id": "b62", "continuation_ref": ref, "reason": "race_cancel"}
    )
    assert cancel.status_code == 409
    assert cancel.body["error"]["code"] == "continuation_claimed"
    assert runtime.call_count == 1

    runtime.release.set()
    resume = await resume_task
    assert resume.status_code == 200
    assert runtime.call_count == 1
    assert store._records[ref].state == "consumed"
    assert store._records[ref].claim_token is None


async def test_cancel_wins_first_resume_is_rejected_without_core_execution() -> None:
    runtime = ImmediateRuntime()
    service, store, ref = _service(runtime)

    cancel = await service.cancel_payload(
        {"app_id": "b62", "continuation_ref": ref, "reason": "race_cancel"}
    )
    resume = await service.resume_payload(_payload(ref))

    assert cancel.status_code == 200
    assert resume.status_code == 409
    assert resume.body["error"]["code"] == "continuation_cancelled"
    assert runtime.call_count == 0
    assert store._records[ref].state == "cancelled"
    assert store._records[ref].claim_token is None


async def test_repeated_cancel_resume_races_have_single_winner_and_no_claim_leak() -> None:
    for _ in range(25):
        runtime = ImmediateRuntime()
        service, store, ref = _service(runtime)
        resume_payload = _payload(ref)
        cancel_payload = {"app_id": "b62", "continuation_ref": ref, "reason": "race_cancel"}

        resume, cancel = await asyncio.gather(
            service.resume_payload(resume_payload),
            service.cancel_payload(cancel_payload),
        )

        successes = sum(response.status_code == 200 for response in (resume, cancel))
        assert successes == 1
        assert runtime.call_count in {0, 1}
        assert store._records[ref].state in {"consumed", "cancelled"}
        assert store._records[ref].claim_token is None
