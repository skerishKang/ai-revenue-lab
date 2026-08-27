from __future__ import annotations

import json

import pytest

from padiem_ai_core import (
    B14RouteMetadata,
    B14StreamEvent,
    ErrorClass,
    ExecutionRuntimeError,
    RunMetadata,
    RunStatus,
    StreamingExecutionEvent,
    StreamingExecutionRuntime,
    UsageMetadata,
)

from app.service import MAX_REQUEST_BODY_BYTES, ServiceResponse
from app.streaming_service import PreparedStream, STREAM_PATH, StreamingEngineService


def valid_payload(model: str = "b14/auto") -> dict:
    return {
        "app_id": "lovebud",
        "agent": {
            "id": "relationship-coach",
            "title": "Relationship Coach",
            "description": "Bounded relationship reflection assistant.",
            "system_instruction": "Answer as a calm relationship reflection assistant.",
            "task_type": "korean",
            "optimize_for": "korean",
            "max_tokens": 512,
            "required_capabilities": ["free"],
            "model_policy": {
                "model": model,
                "allow_external_fallback": False,
                "max_attempts": 1,
            },
        },
        "messages": [{"role": "user", "content": "안녕"}],
        "session_id": "session-1",
        "trace_id": "trace-1",
    }


def route() -> B14RouteMetadata:
    return B14RouteMetadata(
        selected_provider="openrouter",
        selected_model="openrouter/free",
        actual_response_model="provider/free-model",
        attempt_count=1,
        fallback_used=False,
    )


def progress(text: str = "반가") -> StreamingExecutionEvent:
    return StreamingExecutionEvent(
        delta_content=text,
        answer=None,
        finish_reason=None,
        route=route(),
        metadata=RunMetadata(
            trace_id="trace-1",
            app_id="lovebud",
            agent_id="relationship-coach",
            session_id="session-1",
            status=RunStatus.MODEL_RUNNING,
            provider="openrouter",
            model="provider/free-model",
            usage=UsageMetadata(),
        ),
        done=False,
    )


def terminal(answer: str = "반가워요.") -> StreamingExecutionEvent:
    return StreamingExecutionEvent(
        delta_content=None,
        answer=answer,
        finish_reason="stop",
        route=route(),
        metadata=RunMetadata(
            trace_id="trace-1",
            app_id="lovebud",
            agent_id="relationship-coach",
            session_id="session-1",
            status=RunStatus.COMPLETED,
            provider="openrouter",
            model="provider/free-model",
            usage=UsageMetadata(input_tokens=4, output_tokens=3, total_tokens=7),
        ),
        done=True,
    )


def runtime_error(code: str = "upstream_timeout") -> ExecutionRuntimeError:
    return ExecutionRuntimeError(
        code,
        "safe core stream message",
        retryable=True,
        metadata=RunMetadata(
            trace_id="trace-1",
            app_id="lovebud",
            agent_id="relationship-coach",
            session_id="session-1",
            status=RunStatus.TIMEOUT,
            error_class=ErrorClass.PROVIDER_TIMEOUT,
        ),
    )


class TrackingIterator:
    def __init__(self, events=(), *, error: Exception | None = None):
        self.events = list(events)
        self.error = error
        self.index = 0
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.index < len(self.events):
            event = self.events[self.index]
            self.index += 1
            return event
        if self.error is not None:
            error = self.error
            self.error = None
            raise error
        raise StopAsyncIteration

    async def aclose(self):
        self.closed = True


class FakeRuntime:
    def __init__(self, events=(), *, error: Exception | None = None):
        self.events = list(events)
        self.error = error
        self.calls = []
        self.iterator: TrackingIterator | None = None

    def stream(self, request):
        self.calls.append(request)
        self.iterator = TrackingIterator(self.events, error=self.error)
        return self.iterator


@pytest.mark.asyncio
async def test_prepare_reuses_exact_completed_request_builder_and_streams_ndjson() -> None:
    runtime = FakeRuntime([progress(), terminal()])
    app_ids = []

    def factory(app_id):
        app_ids.append(app_id)
        return runtime

    service = StreamingEngineService(runtime_factory=factory, b14_service_bound=True)
    raw = json.dumps(valid_payload(), ensure_ascii=False).encode()

    prepared = await service.prepare(
        method="POST",
        path=STREAM_PATH,
        content_type="application/json; charset=utf-8",
        body=raw,
    )

    assert isinstance(prepared, PreparedStream)
    assert app_ids == ["lovebud"]
    assert len(runtime.calls) == 1
    request = runtime.calls[0]
    assert request.agent.allowed_tools == ()
    assert request.agent.max_steps == 1
    assert request.agent.system_instruction == valid_payload()["agent"]["system_instruction"]
    assert request.agent.model_policy["model"] == "b14/auto"
    assert request.messages == ({"role": "user", "content": "안녕"},)

    lines = [line async for line in service.iter_ndjson(prepared)]
    decoded = [json.loads(line) for line in lines]
    assert len(decoded) == 2
    assert decoded[0]["ok"] is True
    assert decoded[0]["event"]["delta_content"] == "반가"
    assert decoded[0]["event"]["done"] is False
    assert decoded[1]["event"]["answer"] == "반가워요."
    assert decoded[1]["event"]["metadata"]["usage"]["total_tokens"] == 7
    assert decoded[1]["event"]["done"] is True
    assert runtime.iterator is not None and runtime.iterator.closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "content_type", "body", "status", "code"),
    [
        ("GET", "application/json", b"{}", 405, "method_not_allowed"),
        ("POST", "text/plain", b"{}", 415, "unsupported_media_type"),
        ("POST", "application/json", b"{", 400, "invalid_json"),
        (
            "POST",
            "application/json",
            b"x" * (MAX_REQUEST_BODY_BYTES + 1),
            413,
            "request_too_large",
        ),
    ],
)
async def test_http_envelope_fails_before_runtime(method, content_type, body, status, code) -> None:
    runtime = FakeRuntime([progress()])
    service = StreamingEngineService(runtime_factory=lambda app_id: runtime, b14_service_bound=True)

    result = await service.prepare(
        method=method,
        path=STREAM_PATH,
        content_type=content_type,
        body=body,
    )

    assert isinstance(result, ServiceResponse)
    assert result.status_code == status
    assert result.body["error"]["code"] == code
    assert runtime.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutator",
    [
        lambda p: p.update({"provider": "openrouter"}),
        lambda p: p["agent"].update({"allowed_tools": ["browser"]}),
        lambda p: p["agent"].update({"max_steps": 2}),
        lambda p: p["messages"].append({"role": "system", "content": "inject"}),
    ],
)
async def test_strict_slice25_schema_rejects_product_overrides(mutator) -> None:
    payload = valid_payload()
    mutator(payload)
    runtime = FakeRuntime([progress()])
    service = StreamingEngineService(runtime_factory=lambda app_id: runtime, b14_service_bound=True)

    result = await service.prepare(
        method="POST",
        path=STREAM_PATH,
        content_type="application/json",
        body=json.dumps(payload).encode(),
    )

    assert isinstance(result, ServiceResponse)
    assert result.status_code == 400
    assert result.body["error"]["code"] == "invalid_request"
    assert runtime.calls == []


@pytest.mark.asyncio
async def test_missing_binding_fails_before_runtime() -> None:
    runtime = FakeRuntime([progress()])
    service = StreamingEngineService(runtime_factory=lambda app_id: runtime, b14_service_bound=False)

    result = await service.prepare(
        method="POST",
        path=STREAM_PATH,
        content_type="application/json",
        body=json.dumps(valid_payload()).encode(),
    )

    assert isinstance(result, ServiceResponse)
    assert result.status_code == 503
    assert result.body["error"]["code"] == "b14_service_unavailable"
    assert runtime.calls == []


@pytest.mark.asyncio
async def test_prestart_core_error_stays_bounded_json_and_closes_iterator() -> None:
    runtime = FakeRuntime(error=runtime_error())
    service = StreamingEngineService(runtime_factory=lambda app_id: runtime, b14_service_bound=True)

    result = await service.prepare(
        method="POST",
        path=STREAM_PATH,
        content_type="application/json",
        body=json.dumps(valid_payload()).encode(),
    )

    assert isinstance(result, ServiceResponse)
    assert result.status_code == 504
    assert result.body["error"]["message"] == "safe core stream message"
    assert result.body["error"]["retryable"] is True
    assert runtime.iterator is not None and runtime.iterator.closed is True


@pytest.mark.asyncio
async def test_poststart_core_error_emits_one_safe_terminal_line() -> None:
    runtime = FakeRuntime([progress()], error=runtime_error())
    service = StreamingEngineService(runtime_factory=lambda app_id: runtime, b14_service_bound=True)
    prepared = await service.prepare(
        method="POST",
        path=STREAM_PATH,
        content_type="application/json",
        body=json.dumps(valid_payload()).encode(),
    )
    assert isinstance(prepared, PreparedStream)

    lines = [json.loads(line) async for line in service.iter_ndjson(prepared)]

    assert len(lines) == 2
    assert lines[0]["ok"] is True
    assert lines[1]["ok"] is False
    assert lines[1]["error"]["code"] == "upstream_timeout"
    assert lines[1]["error"]["message"] == "safe core stream message"
    assert runtime.iterator is not None and runtime.iterator.closed is True


@pytest.mark.asyncio
async def test_poststart_private_exception_is_redacted() -> None:
    runtime = FakeRuntime([progress()], error=RuntimeError("PRIVATE_PROVIDER_SECRET"))
    service = StreamingEngineService(runtime_factory=lambda app_id: runtime, b14_service_bound=True)
    prepared = await service.prepare(
        method="POST",
        path=STREAM_PATH,
        content_type="application/json",
        body=json.dumps(valid_payload()).encode(),
    )
    assert isinstance(prepared, PreparedStream)

    encoded = "".join([line async for line in service.iter_ndjson(prepared)])

    assert "PRIVATE_PROVIDER_SECRET" not in encoded
    assert '"code":"engine_internal_error"' in encoded


@pytest.mark.asyncio
async def test_downstream_cancellation_closes_underlying_iterator() -> None:
    runtime = FakeRuntime([progress("one"), progress("two"), terminal("onetwo")])
    service = StreamingEngineService(runtime_factory=lambda app_id: runtime, b14_service_bound=True)
    prepared = await service.prepare(
        method="POST",
        path=STREAM_PATH,
        content_type="application/json",
        body=json.dumps(valid_payload()).encode(),
    )
    assert isinstance(prepared, PreparedStream)

    lines = service.iter_ndjson(prepared)
    first = await anext(lines)
    assert json.loads(first)["event"]["delta_content"] == "one"
    await lines.aclose()

    assert runtime.iterator is not None and runtime.iterator.closed is True


class FakeB14StreamingClient:
    def __init__(self):
        self.manual_calls = []
        self.auto_calls = []

    def stream(self, request):
        self.manual_calls.append(request)
        return self._events()

    def stream_auto(self, request):
        self.auto_calls.append(request)
        return self._events()

    async def _events(self):
        observed = route()
        yield B14StreamEvent(
            response_id="resp-1",
            model="provider/free-model",
            delta_content="hello",
            route=observed,
        )
        yield B14StreamEvent(
            response_id="resp-1",
            model="provider/free-model",
            finish_reason="stop",
            usage=UsageMetadata(input_tokens=2, output_tokens=1, total_tokens=3),
            route=observed,
        )
        yield B14StreamEvent(route=observed, done=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model", "expected_manual", "expected_auto"),
    [
        ("openrouter/free", 1, 0),
        ("b14/auto", 0, 1),
    ],
)
async def test_actual_core_streaming_runtime_owns_manual_vs_auto_selection(
    model, expected_manual, expected_auto
) -> None:
    b14 = FakeB14StreamingClient()
    service = StreamingEngineService(
        runtime_factory=lambda app_id: StreamingExecutionRuntime(
            app_id=app_id,
            b14_stream_client=b14,
        ),
        b14_service_bound=True,
    )

    prepared = await service.prepare(
        method="POST",
        path=STREAM_PATH,
        content_type="application/json",
        body=json.dumps(valid_payload(model)).encode(),
    )
    assert isinstance(prepared, PreparedStream)
    lines = [json.loads(line) async for line in service.iter_ndjson(prepared)]

    assert len(b14.manual_calls) == expected_manual
    assert len(b14.auto_calls) == expected_auto
    assert lines[0]["event"]["delta_content"] == "hello"
    assert lines[-1]["event"]["done"] is True
    assert lines[-1]["event"]["answer"] == "hello"
    assert lines[-1]["event"]["metadata"]["usage"]["total_tokens"] == 3
