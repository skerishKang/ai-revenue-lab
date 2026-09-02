from __future__ import annotations

import asyncio

from padiem_ai_core.b14_execution import B14ExecutionResult
from padiem_ai_core.b14_streaming import B14StreamEvent
from padiem_ai_core.contracts import AgentProfile
from padiem_ai_core.execution_runtime import ExecutionRequest, ExecutionRuntime
from padiem_ai_core.streaming_runtime import StreamingExecutionRuntime


def run(coro):
    return asyncio.run(coro)


def unconstrained_agent() -> AgentProfile:
    return AgentProfile(
        id="unconstrained-agent",
        title="Unconstrained",
        description="No product-owned response shaping",
        system_instruction=None,
        task_type="general",
        optimize_for="korean",
        max_tokens=None,
        model_policy={"model": "openrouter/free"},
    )


class CaptureExecutor:
    def __init__(self):
        self.calls = []

    async def execute(self, request):
        self.calls.append(request)
        return B14ExecutionResult(answer="ok")


class CaptureStreamClient:
    def __init__(self):
        self.calls = []

    async def _events(self):
        yield B14StreamEvent(delta_content="ok")
        yield B14StreamEvent(done=True)

    def stream(self, request):
        self.calls.append(request)
        return self._events()

    def stream_auto(self, request):
        self.calls.append(request)
        return self._events()


async def collect(runtime: StreamingExecutionRuntime, request: ExecutionRequest):
    return [event async for event in runtime.stream(request)]


def request(*, additional_system_context: str | None = None) -> ExecutionRequest:
    return ExecutionRequest(
        agent=unconstrained_agent(),
        messages=({"role": "user", "content": "질문"},),
        additional_system_context=additional_system_context,
    )


def test_agent_profile_accepts_absent_response_constraints() -> None:
    profile = unconstrained_agent()

    assert profile.system_instruction is None
    assert profile.max_tokens is None
    assert profile.to_public_dict()["max_tokens"] is None


def test_nonstreaming_execution_omits_system_message_and_max_tokens() -> None:
    executor = CaptureExecutor()
    runtime = ExecutionRuntime(app_id="test-app", b14_client=executor)

    run(runtime.run(request()))

    assert len(executor.calls) == 1
    payload = executor.calls[0].to_payload()
    assert payload["messages"] == [{"role": "user", "content": "질문"}]
    assert "max_tokens" not in payload


def test_streaming_execution_omits_system_message_and_max_tokens() -> None:
    client = CaptureStreamClient()
    runtime = StreamingExecutionRuntime(app_id="test-app", b14_stream_client=client)

    events = run(collect(runtime, request()))

    assert events[-1].done is True
    assert len(client.calls) == 1
    payload = client.calls[0].to_payload()
    assert payload["messages"] == [{"role": "user", "content": "질문"}]
    assert "max_tokens" not in payload


def test_trusted_additional_context_still_uses_one_system_message() -> None:
    executor = CaptureExecutor()
    runtime = ExecutionRuntime(app_id="test-app", b14_client=executor)

    run(runtime.run(request(additional_system_context="Trusted project context.")))

    payload = executor.calls[0].to_payload()
    assert payload["messages"] == [
        {"role": "system", "content": "Trusted project context."},
        {"role": "user", "content": "질문"},
    ]
    assert "max_tokens" not in payload


def test_explicit_constraints_remain_backward_compatible() -> None:
    profile = AgentProfile(
        id="bounded-agent",
        title="Bounded",
        description="Explicit legacy constraints",
        system_instruction="Answer carefully.",
        task_type="general",
        optimize_for="balanced",
        max_tokens=700,
        model_policy={"model": "openrouter/free"},
    )
    executor = CaptureExecutor()
    runtime = ExecutionRuntime(app_id="test-app", b14_client=executor)
    req = ExecutionRequest(
        agent=profile,
        messages=({"role": "user", "content": "question"},),
    )

    run(runtime.run(req))

    payload = executor.calls[0].to_payload()
    assert payload["messages"][0] == {
        "role": "system",
        "content": "Answer carefully.",
    }
    assert payload["max_tokens"] == 700
