from __future__ import annotations

from dataclasses import replace

import pytest

from padiem_ai_core.agent_planner import AgentPlan, AgentPlanStep
from padiem_ai_core.agent_recovery import AgentRecoveryPolicy
from padiem_ai_core.b14_execution import B14RouteMetadata
from padiem_ai_core.contracts import AgentProfile, RunMetadata, RunStatus
from padiem_ai_core.execution_context import (
    ExecutionContext,
    IdempotencyConflictError,
)
from padiem_ai_core.execution_runtime import ExecutionRequest, ExecutionResult
from padiem_ai_core.logical_execution_identity import (
    canonical_logical_execution_fingerprint,
)
from padiem_ai_core.orchestration import OrchestrationRequest, OrchestrationRunner


def _agent(**overrides) -> AgentProfile:
    values = {
        "id": "general-assistant",
        "title": "General Assistant",
        "description": "Handles bounded general tasks.",
        "system_instruction": "Answer carefully.",
        "task_type": "general",
        "optimize_for": "balanced",
        "max_tokens": 1000,
        "allowed_tools": (),
        "required_capabilities": ("chat",),
        "context_policy": {"memory": "bounded"},
        "model_policy": {"model": "b14/auto", "temperature": 0.2},
        "max_steps": 5,
        "output_contract": {"type": "text"},
    }
    values.update(overrides)
    return AgentProfile(**values)


def _execution(
    trace_id: str,
    *,
    agent: AgentProfile | None = None,
    message: str = "hello",
    session_id: str = "session-a",
    system_context: str = "trusted product context",
) -> ExecutionRequest:
    return ExecutionRequest(
        agent=agent or _agent(),
        messages=({"role": "user", "content": message},),
        session_id=session_id,
        additional_system_context=system_context,
        trace_id=trace_id,
    )


def _plan(objective: str = "answer") -> AgentPlan:
    return AgentPlan(
        agent_id="agent:padiem:test@1",
        steps=(AgentPlanStep(step_id="step1", objective=objective),),
    )


def _fingerprint(
    *,
    trace_id: str = "trace-a",
    idempotency_key: str = "idem-a",
    app_id: str = "app-a",
    agent: AgentProfile | None = None,
    message: str = "hello",
    session_id: str = "session-a",
    system_context: str = "trusted product context",
    timeout_seconds: float = 10.0,
    subject_id: str | None = "subject-a",
    plan: AgentPlan | None = None,
    recovery_policy: AgentRecoveryPolicy | None = None,
    max_retries: int = 3,
    require_evidence: bool = False,
    require_verification: bool = False,
) -> str:
    request = _execution(
        trace_id,
        agent=agent,
        message=message,
        session_id=session_id,
        system_context=system_context,
    )
    context = ExecutionContext(
        trace_id=trace_id,
        idempotency_key=idempotency_key,
        timeout_seconds=timeout_seconds,
    )
    return canonical_logical_execution_fingerprint(
        app_id=app_id,
        request=request,
        context=context,
        subject_id=subject_id,
        plan=plan,
        recovery_policy=recovery_policy,
        max_retries=max_retries,
        require_evidence=require_evidence,
        require_verification=require_verification,
    )


def test_trace_and_idempotency_key_are_not_logical_execution_semantics() -> None:
    baseline = _fingerprint(trace_id="trace-a", idempotency_key="key-a")
    retry = _fingerprint(trace_id="trace-b", idempotency_key="key-b")
    assert retry == baseline


@pytest.mark.parametrize(
    "change",
    [
        {"app_id": "app-b"},
        {"agent": _agent(system_instruction="Different trusted instruction.")},
        {"message": "different message"},
        {"session_id": "session-b"},
        {"system_context": "different trusted product context"},
        {"timeout_seconds": 11.0},
        {"subject_id": "subject-b"},
        {"plan": _plan("different objective")},
        {
            "recovery_policy": AgentRecoveryPolicy(
                retryable_driver_codes=("driver_busy",),
                max_retries_per_step=1,
            )
        },
        {"max_retries": 4},
        {"require_evidence": True},
        {"require_verification": True},
    ],
)
def test_material_execution_change_changes_fingerprint(change: dict[str, object]) -> None:
    assert _fingerprint(**change) != _fingerprint()


class _RecordingRuntime:
    def __init__(self) -> None:
        self.calls: list[ExecutionRequest] = []

    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        self.calls.append(request)
        return ExecutionResult(
            answer="runtime answer",
            route=B14RouteMetadata(
                selected_provider="test-provider",
                selected_model="test-model",
            ),
            metadata=RunMetadata(
                trace_id=request.trace_id or "trace-missing",
                app_id="app-a",
                agent_id=request.agent.id,
                session_id=request.session_id,
                status=RunStatus.COMPLETED,
            ),
        )


class _StrictIdempotencyAdapter:
    def __init__(self) -> None:
        self.store: dict[tuple[str, str], tuple[str, ExecutionResult]] = {}

    async def begin(
        self,
        *,
        app_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> ExecutionResult | None:
        stored = self.store.get((app_id, idempotency_key))
        if stored is None:
            return None
        stored_fingerprint, result = stored
        if stored_fingerprint != request_fingerprint:
            raise IdempotencyConflictError("fingerprint mismatch")
        return result

    async def commit(
        self,
        *,
        app_id: str,
        idempotency_key: str,
        request_fingerprint: str,
        result: ExecutionResult,
    ) -> None:
        self.store[(app_id, idempotency_key)] = (request_fingerprint, result)

    async def abort(self, *, app_id: str, idempotency_key: str, reason: str) -> None:
        return None


def _orchestration_request(
    trace_id: str,
    *,
    session_id: str = "session-a",
    subject_id: str = "subject-a",
) -> OrchestrationRequest:
    return OrchestrationRequest(
        execution_request=_execution(trace_id, session_id=session_id),
        context=ExecutionContext(
            trace_id=trace_id,
            idempotency_key="shared-key",
            timeout_seconds=10.0,
        ),
        app_id="app-a",
        subject_id=subject_id,
    )


async def test_direct_core_runner_replays_new_trace_without_rerun() -> None:
    runtime = _RecordingRuntime()
    adapter = _StrictIdempotencyAdapter()
    runner = OrchestrationRunner(runtime=runtime, idempotency=adapter)

    first = await runner.run(_orchestration_request("trace-one"))
    replay = await runner.run(_orchestration_request("trace-two"))

    assert first.execution_result.answer == "runtime answer"
    assert replay.execution_result.answer == "runtime answer"
    assert len(runtime.calls) == 1
    assert replay.events[-1].metadata.get("replay") is True


@pytest.mark.parametrize(
    "changed",
    [
        {"session_id": "session-b"},
        {"subject_id": "subject-b"},
    ],
)
async def test_direct_core_runner_same_key_material_change_conflicts(
    changed: dict[str, str],
) -> None:
    runtime = _RecordingRuntime()
    adapter = _StrictIdempotencyAdapter()
    runner = OrchestrationRunner(runtime=runtime, idempotency=adapter)

    await runner.run(_orchestration_request("trace-one"))

    with pytest.raises(IdempotencyConflictError):
        await runner.run(_orchestration_request("trace-two", **changed))

    assert len(runtime.calls) == 1
