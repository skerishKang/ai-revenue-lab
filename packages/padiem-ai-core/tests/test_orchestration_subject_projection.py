import pytest

from padiem_ai_core import (
    AgentProfile,
    B14RouteMetadata,
    ExecutionContext,
    ExecutionRequest,
    ExecutionResult,
    OrchestrationEventKind,
    OrchestrationRequest,
    OrchestrationRunner,
    RunMetadata,
    RunStatus,
)


class FakeRuntime:
    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        return ExecutionResult(
            answer="subject-safe answer",
            route=B14RouteMetadata(selected_provider="test", selected_model="test"),
            metadata=RunMetadata(
                trace_id=request.trace_id or "trace_subject",
                app_id="b62",
                agent_id=request.agent.id,
                status=RunStatus.COMPLETED,
            ),
        )


def make_agent_profile() -> AgentProfile:
    return AgentProfile(
        id="subject_projection_agent",
        title="Subject Projection Agent",
        description="Validates public subject minimization.",
        system_instruction="Return a bounded answer.",
        task_type="general",
        optimize_for="balanced",
        max_tokens=100,
        max_steps=1,
    )


@pytest.mark.asyncio
async def test_public_orchestration_result_omits_raw_subject_identity_by_default() -> None:
    runner = OrchestrationRunner(runtime=FakeRuntime())
    request = OrchestrationRequest(
        execution_request=ExecutionRequest(
            agent=make_agent_profile(),
            messages=({"role": "user", "content": "hello"},),
            trace_id="trace_subject",
        ),
        context=ExecutionContext(trace_id="trace_subject"),
        app_id="b62",
        subject_id="user@example.com",
    )

    result = await runner.run(request)
    public = result.to_public_dict()
    serialized = repr(public)

    assert result.subject_id == "user@example.com"
    assert "subject_id" not in public
    assert "user@example.com" not in serialized
    assert all("user@example.com" not in repr(event) for event in public["events"])
    assert public["events"][-1]["kind"] == OrchestrationEventKind.RUN_COMPLETED.value
