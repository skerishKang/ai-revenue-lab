"""Regression coverage for idempotency-bound orchestration resume."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from padiem_ai_core import (
    ApprovalOutcome,
    ApprovalPause,
    ApprovalRequirement,
    B14RouteMetadata,
    ExecutionRequest,
    ExecutionResult,
    IdempotencyConflictError,
    RunMetadata,
    RunStatus,
    VerifiedApprovalDecision,
    request_fingerprint,
)

from app.orchestration_service import InMemoryContinuationStore, OrchestrationEngineService


def _agent_payload() -> dict:
    return {
        "id": "agent:padiem:orchestrator_1",
        "title": "Orchestrator",
        "description": "Orchestrates execution",
        "system_instruction": "Execute tasks",
        "task_type": "general",
        "optimize_for": "balanced",
        "max_tokens": 2048,
    }


def _resume_payload(*, idempotency_key: str = "idem_resume") -> dict:
    return {
        "app_id": "b62",
        "agent": _agent_payload(),
        "messages": [{"role": "user", "content": "Hello engine"}],
        "trace_id": "tr_orch_test",
        "execution_context": {
            "trace_id": "tr_orch_test",
            "idempotency_key": idempotency_key,
            "timeout_seconds": 15.0,
        },
        "decision": {
            "decision_id": "dec_resume_1",
            "pause_id": "pause_resume_1",
            "outcome": "approved",
            "authority_ref": "control:approval",
            "evidence_ref": "evidence:approval",
            "decided_at": (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat(),
        },
    }


def _fingerprint() -> str:
    return request_fingerprint(
        {
            "app_id": "b62",
            "agent_id": "agent:padiem:orchestrator_1",
            "messages": [{"role": "user", "content": "Hello engine"}],
        }
    )


def _pause() -> ApprovalPause:
    now = datetime.now(timezone.utc)
    return ApprovalPause(
        pause_id="pause_resume_1",
        run_id="run_resume_1",
        agent_runtime_id="agent:padiem:orchestrator_1",
        tool_id="calc",
        invocation_sha256="0" * 64,
        requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=1,
        created_at=now,
        expires_at=now + timedelta(minutes=10),
        trace_id="tr_orch_test",
    )


def _issue_bound_continuation(
    store: InMemoryContinuationStore,
    *,
    idempotency_key: str = "idem_resume",
    request_fingerprint_value: str | None = None,
) -> str:
    return store.issue(
        app_id="b62",
        pause=_pause(),
        plan_id=None,
        idempotency_key=idempotency_key,
        request_fingerprint=request_fingerprint_value or _fingerprint(),
    )


class CountingRuntime:
    def __init__(self) -> None:
        self.call_count = 0

    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        self.call_count += 1
        return ExecutionResult(
            answer="resumed once",
            route=B14RouteMetadata(selected_provider="mock_provider", selected_model="mock_model"),
            metadata=RunMetadata(
                trace_id=request.trace_id or "tr_orch_test",
                app_id="b62",
                agent_id=request.agent.id,
                status=RunStatus.COMPLETED,
            ),
        )


class RecordingIdempotencyAdapter:
    def __init__(self) -> None:
        self.begin_calls: list[tuple[str, str, str]] = []
        self.complete_calls: list[tuple[str, str, str, str]] = []
        self.records: dict[tuple[str, str], tuple[str, ExecutionResult | None]] = {}

    async def begin(self, *, app_id: str, idempotency_key: str, request_fingerprint: str):
        self.begin_calls.append((app_id, idempotency_key, request_fingerprint))
        record = self.records.get((app_id, idempotency_key))
        if record is None:
            self.records[(app_id, idempotency_key)] = (request_fingerprint, None)
            return None
        existing_fp, result = record
        if existing_fp != request_fingerprint:
            raise IdempotencyConflictError("conflicting request fingerprint")
        return result

    async def complete(self, *, app_id: str, idempotency_key: str, request_fingerprint: str, result):
        assert isinstance(result, ExecutionResult)
        self.complete_calls.append((app_id, idempotency_key, request_fingerprint, result.answer))
        self.records[(app_id, idempotency_key)] = (request_fingerprint, result)

    async def commit(self, **kwargs):
        await self.complete(**kwargs)


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


async def test_bound_idempotency_resume_runs_once_and_commits_once() -> None:
    runtime = CountingRuntime()
    adapter = RecordingIdempotencyAdapter()
    store = InMemoryContinuationStore()
    service = OrchestrationEngineService(
        runtime_factory=lambda app_id: runtime,
        b14_service_bound=True,
        idempotency_adapter=adapter,
        approval_decision_verifier=Verifier(),
        continuation_store=store,
    )
    payload = _resume_payload()
    ref = _issue_bound_continuation(store)
    payload["continuation_ref"] = ref

    response = await service.resume_payload(payload)

    assert response.status_code == 200
    assert response.body["ok"] is True
    assert runtime.call_count == 1
    assert len(adapter.begin_calls) == 1
    assert len(adapter.complete_calls) == 1
    assert adapter.complete_calls[0][1] == "idem_resume"
    assert store._records[ref].state == "consumed"


async def test_bound_idempotency_resume_rejects_key_mismatch_before_rerun() -> None:
    runtime = CountingRuntime()
    adapter = RecordingIdempotencyAdapter()
    store = InMemoryContinuationStore()
    service = OrchestrationEngineService(
        runtime_factory=lambda app_id: runtime,
        b14_service_bound=True,
        idempotency_adapter=adapter,
        approval_decision_verifier=Verifier(),
        continuation_store=store,
    )
    payload = _resume_payload(idempotency_key="idem_client_other")
    ref = _issue_bound_continuation(store, idempotency_key="idem_server")
    payload["continuation_ref"] = ref

    response = await service.resume_payload(payload)

    assert response.status_code == 409
    assert response.body["error"]["code"] == "idempotency_conflict"
    assert runtime.call_count == 0
    assert adapter.begin_calls == []
    assert adapter.complete_calls == []
    assert store._records[ref].state == "active"


async def test_bound_idempotency_resume_rejects_fingerprint_mismatch_before_rerun() -> None:
    runtime = CountingRuntime()
    adapter = RecordingIdempotencyAdapter()
    store = InMemoryContinuationStore()
    service = OrchestrationEngineService(
        runtime_factory=lambda app_id: runtime,
        b14_service_bound=True,
        idempotency_adapter=adapter,
        approval_decision_verifier=Verifier(),
        continuation_store=store,
    )
    payload = _resume_payload()
    ref = _issue_bound_continuation(store, request_fingerprint_value="f" * 64)
    payload["continuation_ref"] = ref

    response = await service.resume_payload(payload)

    assert response.status_code == 409
    assert response.body["error"]["code"] == "idempotency_conflict"
    assert runtime.call_count == 0
    assert adapter.begin_calls == []
    assert adapter.complete_calls == []
    assert store._records[ref].state == "active"


async def test_unbound_resume_rejects_unexpected_idempotency_key_before_rerun() -> None:
    runtime = CountingRuntime()
    adapter = RecordingIdempotencyAdapter()
    store = InMemoryContinuationStore()
    service = OrchestrationEngineService(
        runtime_factory=lambda app_id: runtime,
        b14_service_bound=True,
        idempotency_adapter=adapter,
        approval_decision_verifier=Verifier(),
        continuation_store=store,
    )
    payload = _resume_payload()
    ref = store.issue(app_id="b62", pause=_pause(), plan_id=None)
    payload["continuation_ref"] = ref

    response = await service.resume_payload(payload)

    assert response.status_code == 409
    assert response.body["error"]["code"] == "continuation_identity_mismatch"
    assert runtime.call_count == 0
    assert adapter.begin_calls == []
    assert adapter.complete_calls == []
    assert store._records[ref].state == "active"
