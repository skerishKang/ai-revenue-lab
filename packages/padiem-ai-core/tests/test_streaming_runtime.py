from __future__ import annotations

import asyncio
import json

import pytest

import padiem_ai_core
from padiem_ai_core.b14_execution import B14ExecutionError, B14RouteMetadata
from padiem_ai_core.b14_streaming import B14StreamEvent
from padiem_ai_core.contracts import AgentProfile, ErrorClass, RunStatus, UsageMetadata
from padiem_ai_core.execution_runtime import ExecutionRequest, ExecutionRuntimeError
from padiem_ai_core.streaming_runtime import (
    StreamingExecutionEvent,
    StreamingExecutionRuntime,
)


def run(coro):
    return asyncio.run(coro)


async def collect(runtime: StreamingExecutionRuntime, request: ExecutionRequest):
    return [event async for event in runtime.stream(request)]


def agent(**overrides) -> AgentProfile:
    values = {
        "id": "general-agent",
        "title": "General",
        "description": "General streaming agent",
        "system_instruction": "Answer carefully.",
        "task_type": "general",
        "optimize_for": "korean",
        "max_tokens": 700,
        "required_capabilities": ("free",),
        "model_policy": {},
    }
    values.update(overrides)
    return AgentProfile(**values)


def request(profile=None, **overrides) -> ExecutionRequest:
    values = {
        "agent": profile or agent(),
        "messages": ({"role": "user", "content": "안녕하세요"},),
        "trace_id": "trace-stream-1",
        "session_id": "session-stream-1",
    }
    values.update(overrides)
    return ExecutionRequest(**values)


ROUTE = B14RouteMetadata(
    selected_provider="openrouter",
    selected_model="openrouter/free",
    actual_response_model="provider/free-model",
)


class FakeStreamClient:
    def __init__(self, events=(), *, error=None):
        self.events = tuple(events)
        self.error = error
        self.dispatches = []
        self.closed = 0

    async def _iterate(self):
        try:
            if self.error is not None:
                raise self.error
            for event in self.events:
                yield event
        finally:
            self.closed += 1

    def stream_auto(self, request):
        self.dispatches.append(("auto", request))
        return self._iterate()

    def stream(self, request):
        self.dispatches.append(("manual", request))
        return self._iterate()


def complete_events():
    return (
        B14StreamEvent(delta_content="안녕", route=ROUTE),
        B14StreamEvent(delta_content="하세요", model="provider/free-model", route=ROUTE),
        B14StreamEvent(
            finish_reason="stop",
            usage=UsageMetadata(input_tokens=5, output_tokens=4, total_tokens=9),
            route=ROUTE,
        ),
        B14StreamEvent(route=ROUTE, done=True),
    )


def test_package_root_exports_streaming_runtime_facade() -> None:
    assert padiem_ai_core.StreamingExecutionRuntime is StreamingExecutionRuntime
    assert padiem_ai_core.StreamingExecutionEvent is StreamingExecutionEvent


def test_auto_stream_dispatches_once_and_surfaces_progress_before_completion() -> None:
    client = FakeStreamClient(complete_events())
    runtime = StreamingExecutionRuntime(
        app_id="test-app", b14_stream_client=client, clock=lambda: 10.0
    )

    events = run(collect(runtime, request()))

    assert len(client.dispatches) == 1
    kind, b14_request = client.dispatches[0]
    assert kind == "auto"
    assert b14_request.model == "b14/auto"
    assert [event.delta_content for event in events[:-1]] == ["안녕", "하세요"]
    assert all(event.done is False for event in events[:-1])
    assert all(event.metadata.status is RunStatus.MODEL_RUNNING for event in events[:-1])

    terminal = events[-1]
    assert terminal.done is True
    assert terminal.delta_content is None
    assert terminal.answer == "안녕하세요"
    assert terminal.finish_reason == "stop"
    assert terminal.metadata.status is RunStatus.COMPLETED
    assert terminal.metadata.provider == "openrouter"
    assert terminal.metadata.model == "provider/free-model"
    assert terminal.metadata.usage == UsageMetadata(
        input_tokens=5, output_tokens=4, total_tokens=9
    )
    assert client.closed == 1


def test_manual_stream_uses_explicit_model_and_reuses_completed_request_policy() -> None:
    profile = agent(
        model_policy={
            "model": "openrouter/free",
            "temperature": 0.4,
            "provider_order": ["OpenRouter"],
            "max_attempts": 1,
            "allow_external_fallback": False,
        }
    )
    client = FakeStreamClient(complete_events())
    runtime = StreamingExecutionRuntime(app_id="test-app", b14_stream_client=client)

    run(
        collect(
            runtime,
            request(profile, additional_system_context="Trusted product context."),
        )
    )

    assert len(client.dispatches) == 1
    kind, b14_request = client.dispatches[0]
    assert kind == "manual"
    payload = b14_request.to_payload()
    assert payload["model"] == "openrouter/free"
    assert payload["temperature"] == 0.4
    assert payload["max_tokens"] == 700
    assert payload["messages"] == [
        {
            "role": "system",
            "content": "Answer carefully.\n\nTrusted product context.",
        },
        {"role": "user", "content": "안녕하세요"},
    ]
    assert payload["business14"] == {
        "task_type": "general",
        "required_capabilities": ["free"],
        "optimize_for": "korean",
        "allow_external_fallback": False,
        "provider_order": ["OpenRouter"],
        "max_attempts": 1,
    }


def test_nonempty_tools_fail_before_stream_dispatch() -> None:
    client = FakeStreamClient(complete_events())
    runtime = StreamingExecutionRuntime(app_id="test-app", b14_stream_client=client)

    with pytest.raises(ExecutionRuntimeError) as info:
        run(collect(runtime, request(agent(allowed_tools=("web_search",)))))

    assert info.value.code == "native_tools_unsupported"
    assert info.value.metadata.status is RunStatus.POLICY_BLOCKED
    assert info.value.metadata.error_class is ErrorClass.POLICY_BLOCKED
    assert client.dispatches == []


def test_invalid_model_policy_fails_before_stream_dispatch() -> None:
    client = FakeStreamClient(complete_events())
    runtime = StreamingExecutionRuntime(app_id="test-app", b14_stream_client=client)

    with pytest.raises(ExecutionRuntimeError) as info:
        run(collect(runtime, request(agent(model_policy={"provider": "not-core"}))))

    assert info.value.code == "invalid_execution_request"
    assert info.value.metadata.status is RunStatus.REJECTED
    assert client.dispatches == []


def test_b14_stream_error_is_redacted_and_preserves_retryability() -> None:
    client = FakeStreamClient(
        error=B14ExecutionError(
            "upstream_rate_limited",
            "PRIVATE-UPSTREAM-DETAIL",
            retryable=True,
        )
    )
    runtime = StreamingExecutionRuntime(app_id="test-app", b14_stream_client=client)

    with pytest.raises(ExecutionRuntimeError) as info:
        run(collect(runtime, request()))

    assert len(client.dispatches) == 1
    assert info.value.code == "upstream_rate_limited"
    assert info.value.retryable is True
    assert info.value.metadata.status is RunStatus.FAILED
    assert info.value.metadata.error_class is ErrorClass.PROVIDER_RATE_LIMIT
    assert "PRIVATE-UPSTREAM-DETAIL" not in json.dumps(info.value.to_public_dict())
    assert client.closed == 1


def test_invalid_stream_event_contract_fails_closed() -> None:
    client = FakeStreamClient(({"private": "SECRET"},))
    runtime = StreamingExecutionRuntime(app_id="test-app", b14_stream_client=client)

    with pytest.raises(ExecutionRuntimeError) as info:
        run(collect(runtime, request()))

    assert info.value.code == "invalid_stream_event"
    assert info.value.metadata.error_class is ErrorClass.PROVIDER_BAD_RESPONSE
    assert "SECRET" not in json.dumps(info.value.to_public_dict())
    assert client.closed == 1


def test_done_without_visible_answer_fails_closed() -> None:
    client = FakeStreamClient(
        (
            B14StreamEvent(
                usage=UsageMetadata(input_tokens=2, output_tokens=0, total_tokens=2),
                route=ROUTE,
            ),
            B14StreamEvent(route=ROUTE, done=True),
        )
    )
    runtime = StreamingExecutionRuntime(app_id="test-app", b14_stream_client=client)

    with pytest.raises(ExecutionRuntimeError) as info:
        run(collect(runtime, request()))

    assert info.value.code == "empty_upstream_answer"
    assert info.value.metadata.error_class is ErrorClass.PROVIDER_BAD_RESPONSE
    assert client.closed == 1


def test_stream_end_without_done_marker_fails_closed() -> None:
    client = FakeStreamClient((B14StreamEvent(delta_content="partial", route=ROUTE),))
    runtime = StreamingExecutionRuntime(app_id="test-app", b14_stream_client=client)

    with pytest.raises(ExecutionRuntimeError) as info:
        run(collect(runtime, request()))

    assert info.value.code == "malformed_upstream"
    assert info.value.metadata.provider == "openrouter"
    assert client.closed == 1


def test_partial_error_metadata_keeps_only_observed_route_and_usage() -> None:
    class PartialThenErrorClient(FakeStreamClient):
        async def _iterate(self):
            try:
                yield B14StreamEvent(
                    delta_content="partial",
                    model="provider/free-model",
                    route=ROUTE,
                    usage=UsageMetadata(input_tokens=3),
                )
                raise B14ExecutionError(
                    "upstream_timeout", "PRIVATE-TIMEOUT", retryable=True
                )
            finally:
                self.closed += 1

    client = PartialThenErrorClient()
    runtime = StreamingExecutionRuntime(app_id="test-app", b14_stream_client=client)

    async def consume():
        iterator = runtime.stream(request())
        first = await iterator.__anext__()
        assert first.delta_content == "partial"
        with pytest.raises(ExecutionRuntimeError) as info:
            await iterator.__anext__()
        return info.value

    error = run(consume())
    assert error.code == "upstream_timeout"
    assert error.metadata.status is RunStatus.TIMEOUT
    assert error.metadata.provider == "openrouter"
    assert error.metadata.model == "provider/free-model"
    assert error.metadata.usage.input_tokens == 3
    assert "PRIVATE-TIMEOUT" not in json.dumps(error.to_public_dict())


def test_consumer_close_closes_underlying_stream() -> None:
    class EndlessClient(FakeStreamClient):
        def __init__(self):
            super().__init__()
            self.release = asyncio.Event()

        async def _iterate(self):
            try:
                yield B14StreamEvent(delta_content="first", route=ROUTE)
                await self.release.wait()
                yield B14StreamEvent(delta_content="late", route=ROUTE)
            finally:
                self.closed += 1

    async def scenario():
        client = EndlessClient()
        runtime = StreamingExecutionRuntime(app_id="test-app", b14_stream_client=client)
        iterator = runtime.stream(request())
        first = await iterator.__anext__()
        assert first.delta_content == "first"
        assert client.closed == 0
        await iterator.aclose()
        assert client.closed == 1
        return client

    client = run(scenario())
    assert len(client.dispatches) == 1


def test_stream_event_public_contract_separates_delta_and_terminal_answer() -> None:
    metadata_running = padiem_ai_core.RunMetadata(
        trace_id="trace",
        app_id="app",
        agent_id="agent",
        status=RunStatus.MODEL_RUNNING,
    )
    partial = StreamingExecutionEvent(
        delta_content="x",
        answer=None,
        finish_reason=None,
        route=B14RouteMetadata(),
        metadata=metadata_running,
    )
    assert partial.to_public_dict()["done"] is False

    metadata_done = padiem_ai_core.RunMetadata(
        trace_id="trace",
        app_id="app",
        agent_id="agent",
        status=RunStatus.COMPLETED,
    )
    terminal = StreamingExecutionEvent(
        delta_content=None,
        answer="x",
        finish_reason="stop",
        route=B14RouteMetadata(),
        metadata=metadata_done,
        done=True,
    )
    assert terminal.to_public_dict()["answer"] == "x"

    with pytest.raises(ValueError, match="terminal event"):
        StreamingExecutionEvent(
            delta_content="x",
            answer="x",
            finish_reason=None,
            route=B14RouteMetadata(),
            metadata=metadata_done,
            done=True,
        )
