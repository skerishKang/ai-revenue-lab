from __future__ import annotations

import asyncio
import json

import pytest

from app.service import EngineService
from app.streaming_service import StreamingEngineService
from padiem_ai_core import ExecutionContext, ExecutionResult, RunMetadata


class FakeRuntime:
    def __init__(self, result: ExecutionResult):
        self.result = result
        self.requests = []

    async def run(self, request):
        self.requests.append(request)
        return self.result


class FakeStreamRuntime:
    def __init__(self):
        self.requests = []

    def stream(self, request):
        self.requests.append(request)

        async def iterator():
            yield type("Event", (), {"done": True, "to_public_dict": lambda self: {"done": True}})()

        return iterator()


@pytest.fixture
def result():
    return ExecutionResult(
        answer="ok",
        route=type("Route", (), {"to_public_dict": lambda self: {}})(),
        metadata=RunMetadata(trace_id="run_test", app_id="b62", agent_id="agent", status="completed"),
    )


def payload(**context):
    body = {
        "app_id": "b62",
        "agent": {
            "id": "agent",
            "title": "Agent",
            "description": "Agent",
            "system_instruction": "Answer safely.",
            "task_type": "general",
            "optimize_for": "balanced",
            "max_tokens": 100,
        },
        "messages": [{"role": "user", "content": "hello"}],
    }
    if context:
        body["execution_context"] = context
    return body


@pytest.mark.asyncio
async def test_context_is_accepted_and_trace_propagates(result):
    runtime = FakeRuntime(result)
    service = EngineService(runtime_factory=lambda _: runtime, b14_service_bound=True)
    response = await service.execute_payload(
        payload(trace_id="trace_123", timeout_seconds=5)
    )
    assert response.status_code == 200
    assert runtime.requests[0].trace_id == "trace_123"


@pytest.mark.asyncio
async def test_idempotency_key_fails_closed_without_adapter(result):
    runtime = FakeRuntime(result)
    service = EngineService(runtime_factory=lambda _: runtime, b14_service_bound=True)
    response = await service.execute_payload(
        payload(trace_id="trace_123", idempotency_key="idem_123")
    )
    assert response.status_code == 422
    assert response.body["error"]["code"] == "execution_context_unavailable"
    assert runtime.requests == []


@pytest.mark.asyncio
async def test_trace_conflict_fails_closed(result):
    runtime = FakeRuntime(result)
    service = EngineService(runtime_factory=lambda _: runtime, b14_service_bound=True)
    body = payload(trace_id="top_trace", extra_unused="ignored")
    body.pop("extra_unused", None)
    body["execution_context"] = {"trace_id": "inner_trace"}
    response = await service.execute_payload(body)
    assert response.status_code == 400
    assert response.body["error"]["code"] == "trace_id_conflict"
    assert runtime.requests == []


@pytest.mark.asyncio
async def test_streaming_idempotency_is_explicitly_unavailable():
    runtime = FakeStreamRuntime()
    service = StreamingEngineService(
        runtime_factory=lambda _: runtime,
        b14_service_bound=True,
    )
    response = await service.prepare(
        method="POST",
        path="/internal/v1/stream",
        content_type="application/json",
        body=json.dumps(payload(trace_id="trace_123", idempotency_key="idem_123")).encode(),
    )
    assert response.status_code == 422
    assert response.body["error"]["code"] == "stream_idempotency_unavailable"
    assert runtime.requests == []
