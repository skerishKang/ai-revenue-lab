from __future__ import annotations

import asyncio

import pytest

from padiem_ai_core import (
    B14RouteMetadata,
    ExecutionContext,
    ExecutionResult,
    ExecutionRuntime,
    ExecutionRuntimeError,
    IdempotencyConflictError,
    RunMetadata,
    RunStatus,
)
from padiem_ai_core.contextual_execution import ContextualExecutionRunner, prepare_execution


RESULT = ExecutionResult(
    answer="ok",
    route=B14RouteMetadata(),
    metadata=RunMetadata(
        trace_id="trace-1",
        app_id="b62",
        agent_id="agent",
        status=RunStatus.COMPLETED,
    ),
)

REQUEST_PAYLOAD = {
    "app_id": "b62",
    "agent": {"id": "agent", "model": "b14/auto"},
    "messages": [{"role": "user", "content": "hello"}],
}


class DummyB14:
    async def execute(self, request):
        raise AssertionError("B14 should not be called by the stub runtime")


class StubRuntime(ExecutionRuntime):
    def __init__(self):
        super().__init__(app_id="b62", b14_client=DummyB14())
        self.calls = 0
        self.delay_seconds = 0.0

    async def run(self, request):
        self.calls += 1
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        return RESULT


class MemoryIdempotency:
    def __init__(self):
        self.records = {}

    async def begin(self, *, app_id, idempotency_key, request_fingerprint):
        key = (app_id, idempotency_key)
        current = self.records.get(key)
        if current is None:
            self.records[key] = (request_fingerprint, None)
            return None
        fingerprint, result = current
        if fingerprint != request_fingerprint:
            raise IdempotencyConflictError(
                "idempotency key is bound to a different request"
            )
        return result

    async def complete(self, *, app_id, idempotency_key, request_fingerprint, result):
        key = (app_id, idempotency_key)
        current = self.records.get(key)
        if current is None or current[0] != request_fingerprint:
            raise IdempotencyConflictError("idempotency completion identity mismatch")
        self.records[key] = (request_fingerprint, RESULT)


def prepare_request(trace_id: str = "trace-1"):
    from padiem_ai_core import AgentProfile, ExecutionRequest

    return ExecutionRequest(
        agent=AgentProfile(
            id="agent",
            title="Agent",
            description="Agent",
            system_instruction="Answer safely.",
            task_type="general",
            optimize_for="balanced",
            max_tokens=100,
        ),
        messages=({"role": "user", "content": "hello"},),
        trace_id=trace_id,
    )


def test_prepare_execution_is_deterministic_and_excludes_auth_material() -> None:
    context = ExecutionContext(
        trace_id="trace-123", idempotency_key="idem-123", timeout_seconds=10
    )
    payload_a = {
        **REQUEST_PAYLOAD,
        "authorization": "secret-a",
        "execution_context": {"trace_id": "ignored"},
    }
    payload_b = {
        "messages": [{"content": "hello", "role": "user"}],
        "agent": {"model": "b14/auto", "id": "agent"},
        "app_id": "b62",
        "authorization": "secret-b",
        "execution_context": {"idempotency_key": "other"},
    }

    prepared_a = prepare_execution(context=context, app_id="b62", payload=payload_a)
    prepared_b = prepare_execution(context=context, app_id="b62", payload=payload_b)

    assert prepared_a.request_fingerprint == prepared_b.request_fingerprint
    assert prepared_a.context == context
    assert prepared_a.to_public_dict()["idempotency_present"] is True
    assert "idempotency_key" not in prepared_a.to_public_dict()


def test_prepare_execution_rejects_invalid_context_or_payload() -> None:
    with pytest.raises(ValueError, match="context"):
        prepare_execution(context=object(), app_id="b62", payload={})
    with pytest.raises(ValueError, match="payload"):
        prepare_execution(
            context=ExecutionContext(trace_id="trace-123"),
            app_id="b62",
            payload=[],
        )


@pytest.mark.asyncio
async def test_same_key_same_request_replays_without_second_runtime_call():
    runtime = StubRuntime()
    adapter = MemoryIdempotency()
    runner = ContextualExecutionRunner(runtime=runtime, app_id="b62", idempotency=adapter)
    context = ExecutionContext(trace_id="trace-1", idempotency_key="idem-1")
    request = prepare_request()

    first = await runner.run(request, context=context, request_payload=REQUEST_PAYLOAD)
    second = await runner.run(request, context=context, request_payload=REQUEST_PAYLOAD)

    assert first.answer == second.answer == "ok"
    assert runtime.calls == 1


@pytest.mark.asyncio
async def test_same_key_different_request_fails_closed():
    runtime = StubRuntime()
    adapter = MemoryIdempotency()
    runner = ContextualExecutionRunner(runtime=runtime, app_id="b62", idempotency=adapter)
    context = ExecutionContext(trace_id="trace-1", idempotency_key="idem-1")
    request = prepare_request()

    await runner.run(request, context=context, request_payload=REQUEST_PAYLOAD)
    different = {**REQUEST_PAYLOAD, "messages": [{"role": "user", "content": "different"}]}

    with pytest.raises(IdempotencyConflictError):
        await runner.run(request, context=context, request_payload=different)
    assert runtime.calls == 1


@pytest.mark.asyncio
async def test_timeout_is_normalized_with_trace_metadata():
    runtime = StubRuntime()
    runtime.delay_seconds = 1.05
    runner = ContextualExecutionRunner(runtime=runtime, app_id="b62")

    with pytest.raises(ExecutionRuntimeError) as exc_info:
        await runner.run(
            prepare_request(),
            context=ExecutionContext(trace_id="trace-timeout", timeout_seconds=1),
            request_payload=REQUEST_PAYLOAD,
        )

    exc = exc_info.value
    assert exc.code == "execution_timeout"
    assert exc.retryable is False
    assert exc.metadata.trace_id == "trace-timeout"
    assert exc.metadata.status is RunStatus.TIMEOUT
    assert exc.metadata.error_class.value == "context_error"


@pytest.mark.asyncio
async def test_cancellation_propagates_instead_of_becoming_internal_error():
    runtime = StubRuntime()
    runtime.delay_seconds = 10
    runner = ContextualExecutionRunner(runtime=runtime, app_id="b62")
    task = asyncio.create_task(
        runner.run(
            prepare_request(),
            context=ExecutionContext(trace_id="trace-cancel", timeout_seconds=60),
            request_payload=REQUEST_PAYLOAD,
        )
    )
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
