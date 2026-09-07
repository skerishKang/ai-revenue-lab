"""Streaming idempotency replay conformance tests (#2025).

Covers all 8 contract scenarios:
  (a) No idempotency key -> adapter calls 0, original streaming behavior.
  (b) Key present but idempotency_adapter is None -> 422 stream_idempotency_unavailable.
  (c) New key -> begin() called once, stream finishes normally -> complete() called once, abort() 0.
  (d) Same key + same payload replay -> begin() returns stored ExecutionResult ->
      exact 1 NDJSON event line with done=True and replayed=True, runtime calls 0.
  (e) Same key + different payload -> 409 idempotency_conflict.
  (f) Mid-stream runtime error -> abort() called once, complete() 0.
  (g) Consumer closes iterator early via aclose() -> abort() called once, complete() 0.
  (h) Iterator exhausts before emitting done=True event -> abort() called once, complete() 0.
"""

from __future__ import annotations

import json
from typing import Any
import pytest

from padiem_ai_core import (
    B14RouteMetadata,
    ErrorClass,
    ExecutionResult,
    ExecutionRuntimeError,
    IdempotencyConflictError,
    RunMetadata,
    RunStatus,
    StreamingExecutionEvent,
    UsageMetadata,
)

from app.service import ServiceResponse
from app.streaming_service import PreparedStream, STREAM_PATH, StreamingEngineService


def _payload(
    key: str | None = None,
    content: str = "안녕",
    app_id: str = "lovebud",
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "app_id": app_id,
        "agent": {
            "id": "relationship-coach",
            "title": "Relationship Coach",
            "description": "Bounded assistant.",
            "system_instruction": "Answer calmly.",
            "task_type": "korean",
            "optimize_for": "korean",
            "max_tokens": 512,
            "required_capabilities": ["free"],
            "model_policy": {
                "model": "b14/auto",
                "allow_external_fallback": False,
                "max_attempts": 1,
            },
        },
        "messages": [{"role": "user", "content": content}],
        "session_id": "session-1",
        "trace_id": "trace-1",
    }
    if key is not None:
        data["execution_context"] = {
            "trace_id": "trace-1",
            "idempotency_key": key,
        }
    return data


def _route() -> B14RouteMetadata:
    return B14RouteMetadata(
        selected_provider="openrouter",
        selected_model="openrouter/free",
        actual_response_model="provider/free-model",
        attempt_count=1,
        fallback_used=False,
    )


def _progress(text: str = "반가") -> StreamingExecutionEvent:
    return StreamingExecutionEvent(
        delta_content=text,
        answer=None,
        finish_reason=None,
        route=_route(),
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


def _terminal(answer: str = "반가워요.") -> StreamingExecutionEvent:
    return StreamingExecutionEvent(
        delta_content=None,
        answer=answer,
        finish_reason="stop",
        route=_route(),
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


class _TrackingIterator:
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


class _FakeRuntime:
    def __init__(self, events=(), *, error: Exception | None = None):
        self.events = list(events)
        self.error = error
        self.calls: list[Any] = []
        self.iterator: _TrackingIterator | None = None

    def stream(self, request: Any):
        self.calls.append(request)
        self.iterator = _TrackingIterator(self.events, error=self.error)
        return self.iterator


class _InMemoryIdempotencyAdapter:
    def __init__(self) -> None:
        self.reservations: dict[tuple[str, str], tuple[str, str, Any]] = {}
        self.begin_calls: list[dict[str, Any]] = []
        self.complete_calls: list[dict[str, Any]] = []
        self.abort_calls: list[dict[str, Any]] = []

    async def begin(
        self,
        *,
        app_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> ExecutionResult | None:
        self.begin_calls.append(
            {
                "app_id": app_id,
                "idempotency_key": idempotency_key,
                "request_fingerprint": request_fingerprint,
            }
        )
        record = self.reservations.get((app_id, idempotency_key))
        if record is not None:
            bound_fp, state, result = record
            if bound_fp != request_fingerprint:
                raise IdempotencyConflictError("idempotency key is bound to a different request")
            if state == "completed" and result is not None:
                return result
            raise IdempotencyConflictError("idempotency key is already reserved")

        self.reservations[(app_id, idempotency_key)] = (
            request_fingerprint,
            "reserved",
            None,
        )
        return None

    async def complete(
        self,
        *,
        app_id: str,
        idempotency_key: str,
        request_fingerprint: str,
        result: dict[str, Any],
    ) -> None:
        self.complete_calls.append(
            {
                "app_id": app_id,
                "idempotency_key": idempotency_key,
                "request_fingerprint": request_fingerprint,
                "result": result,
            }
        )
        record = self.reservations.get((app_id, idempotency_key))
        if record is None or record[0] != request_fingerprint:
            raise IdempotencyConflictError("completion does not match reservation")
        route_meta = B14RouteMetadata(**result.get("route", {}))
        meta = RunMetadata(
            trace_id=result.get("metadata", {}).get("trace_id", "trace-1"),
            app_id=app_id,
            agent_id=result.get("metadata", {}).get("agent_id", "agent-1"),
            status=RunStatus(result.get("metadata", {}).get("status", RunStatus.COMPLETED.value)),
        )
        exec_result = ExecutionResult(
            answer=result["answer"],
            route=route_meta,
            metadata=meta,
        )
        self.reservations[(app_id, idempotency_key)] = (
            request_fingerprint,
            "completed",
            exec_result,
        )

    async def abort(
        self,
        *,
        app_id: str,
        idempotency_key: str,
        reason: str | None = None,
    ) -> None:
        self.abort_calls.append(
            {
                "app_id": app_id,
                "idempotency_key": idempotency_key,
                "reason": reason,
            }
        )
        record = self.reservations.get((app_id, idempotency_key))
        if record is not None and record[1] != "completed":
            self.reservations[(app_id, idempotency_key)] = (
                record[0],
                "aborted",
                None,
            )


@pytest.mark.asyncio
async def test_streaming_no_key_zero_adapter_calls() -> None:
    # (a) 키 없음 -> 어댑터 호출 0, 기존 동작.
    adapter = _InMemoryIdempotencyAdapter()
    runtime = _FakeRuntime([_progress(), _terminal()])
    service = StreamingEngineService(
        runtime_factory=lambda app_id: runtime,
        b14_service_bound=True,
        idempotency_adapter=adapter,
    )

    prepared = await service.prepare(
        method="POST",
        path=STREAM_PATH,
        content_type="application/json",
        body=json.dumps(_payload(key=None)).encode(),
    )
    assert isinstance(prepared, PreparedStream)
    assert prepared.replayed is False
    lines = [line async for line in service.iter_ndjson(prepared)]
    assert len(lines) == 2
    assert len(adapter.begin_calls) == 0
    assert len(adapter.complete_calls) == 0
    assert len(adapter.abort_calls) == 0


@pytest.mark.asyncio
async def test_streaming_adapter_none_with_key_fails_422() -> None:
    # (b) 어댑터 None + 키 -> 422 stream_idempotency_unavailable.
    runtime = _FakeRuntime([_progress(), _terminal()])
    service = StreamingEngineService(
        runtime_factory=lambda app_id: runtime,
        b14_service_bound=True,
        idempotency_adapter=None,
    )

    result = await service.prepare(
        method="POST",
        path=STREAM_PATH,
        content_type="application/json",
        body=json.dumps(_payload(key="key-1")).encode(),
    )
    assert isinstance(result, ServiceResponse)
    assert result.status_code == 422
    assert result.body["error"]["code"] == "stream_idempotency_unavailable"
    assert runtime.calls == []


@pytest.mark.asyncio
async def test_streaming_new_key_normal_completion_records_execution_result() -> None:
    # (c) 신규 키 -> begin 1회, 스트림 정상 완료 -> complete 1회, abort 0, 저장된 ExecutionResult.answer == 마지막 이벤트 answer.
    adapter = _InMemoryIdempotencyAdapter()
    runtime = _FakeRuntime([_progress("반가"), _terminal("반가워요.")])
    service = StreamingEngineService(
        runtime_factory=lambda app_id: runtime,
        b14_service_bound=True,
        idempotency_adapter=adapter,
    )

    prepared = await service.prepare(
        method="POST",
        path=STREAM_PATH,
        content_type="application/json",
        body=json.dumps(_payload(key="key-new-1")).encode(),
    )
    assert isinstance(prepared, PreparedStream)
    assert len(adapter.begin_calls) == 1
    assert adapter.begin_calls[0]["idempotency_key"] == "key-new-1"

    lines = [line async for line in service.iter_ndjson(prepared)]
    assert len(lines) == 2
    assert len(adapter.complete_calls) == 1
    assert len(adapter.abort_calls) == 0
    assert adapter.complete_calls[0]["idempotency_key"] == "key-new-1"
    assert adapter.complete_calls[0]["result"]["answer"] == "반가워요."


@pytest.mark.asyncio
async def test_streaming_replay_same_key_emits_single_event_without_runtime() -> None:
    # (d) 같은 키+같은 payload 재요청 -> begin 이 저장 결과 반환 -> 정확히 1 NDJSON 라인, done=true, replayed 표시, 런타임 호출 0.
    adapter = _InMemoryIdempotencyAdapter()
    runtime1 = _FakeRuntime([_progress("안녕"), _terminal("안녕하세요!")])
    service1 = StreamingEngineService(
        runtime_factory=lambda app_id: runtime1,
        b14_service_bound=True,
        idempotency_adapter=adapter,
    )

    # First run: completes and stores
    payload = _payload(key="key-replay-1", content="안녕")
    prepared1 = await service1.prepare(
        method="POST",
        path=STREAM_PATH,
        content_type="application/json",
        body=json.dumps(payload).encode(),
    )
    assert isinstance(prepared1, PreparedStream)
    _ = [line async for line in service1.iter_ndjson(prepared1)]
    assert len(adapter.complete_calls) == 1

    # Second run with exact same payload and key
    runtime2 = _FakeRuntime([_progress("다름"), _terminal("다름")])
    service2 = StreamingEngineService(
        runtime_factory=lambda app_id: runtime2,
        b14_service_bound=True,
        idempotency_adapter=adapter,
    )
    prepared2 = await service2.prepare(
        method="POST",
        path=STREAM_PATH,
        content_type="application/json",
        body=json.dumps(payload).encode(),
    )
    assert isinstance(prepared2, PreparedStream)
    assert prepared2.replayed is True
    assert len(runtime2.calls) == 0  # No runtime invocation

    lines = [json.loads(line) async for line in service2.iter_ndjson(prepared2)]
    assert len(lines) == 1
    event_data = lines[0]
    assert event_data["ok"] is True
    assert event_data.get("replayed") is True
    assert event_data["event"]["done"] is True
    assert event_data["event"]["answer"] == "안녕하세요!"
    assert event_data["event"]["delta_content"] is None


@pytest.mark.asyncio
async def test_streaming_replay_conflict_with_different_payload() -> None:
    # (e) 같은 키+다른 payload -> 충돌 오류(409 idempotency_conflict).
    adapter = _InMemoryIdempotencyAdapter()
    runtime = _FakeRuntime([_progress("안녕"), _terminal("안녕하세요!")])
    service = StreamingEngineService(
        runtime_factory=lambda app_id: runtime,
        b14_service_bound=True,
        idempotency_adapter=adapter,
    )

    # First request reserves the key
    payload1 = _payload(key="key-conflict-1", content="첫번째 요청")
    prepared1 = await service.prepare(
        method="POST",
        path=STREAM_PATH,
        content_type="application/json",
        body=json.dumps(payload1).encode(),
    )
    assert isinstance(prepared1, PreparedStream)

    # Second request with different content
    payload2 = _payload(key="key-conflict-1", content="두번째 다른 요청")
    result2 = await service.prepare(
        method="POST",
        path=STREAM_PATH,
        content_type="application/json",
        body=json.dumps(payload2).encode(),
    )
    assert isinstance(result2, ServiceResponse)
    assert result2.status_code == 409
    assert result2.body["error"]["code"] == "idempotency_conflict"


@pytest.mark.asyncio
async def test_streaming_midstream_exception_triggers_abort() -> None:
    # (f) 스트림 중간 런타임 예외 -> abort 1회, complete 0.
    adapter = _InMemoryIdempotencyAdapter()
    err = ExecutionRuntimeError(
        "provider_error",
        "Boom",
        retryable=False,
        metadata=RunMetadata(
            trace_id="trace-1",
            app_id="lovebud",
            agent_id="relationship-coach",
            status=RunStatus.FAILED,
            error_class=ErrorClass.PROVIDER_BAD_RESPONSE,
        ),
    )
    runtime = _FakeRuntime([_progress("첫토큰")], error=err)
    service = StreamingEngineService(
        runtime_factory=lambda app_id: runtime,
        b14_service_bound=True,
        idempotency_adapter=adapter,
    )

    prepared = await service.prepare(
        method="POST",
        path=STREAM_PATH,
        content_type="application/json",
        body=json.dumps(_payload(key="key-err-1")).encode(),
    )
    assert isinstance(prepared, PreparedStream)

    lines = [json.loads(line) async for line in service.iter_ndjson(prepared)]
    assert len(lines) == 2
    assert lines[0]["ok"] is True
    assert lines[1]["ok"] is False
    assert lines[1]["error"]["code"] == "provider_error"

    assert len(adapter.complete_calls) == 0
    assert len(adapter.abort_calls) == 1
    assert adapter.abort_calls[0]["idempotency_key"] == "key-err-1"


@pytest.mark.asyncio
async def test_streaming_consumer_early_aclose_triggers_abort() -> None:
    # (g) 소비자가 도중에 aclose()(disconnect 모사) -> abort 1회, complete 0.
    adapter = _InMemoryIdempotencyAdapter()
    runtime = _FakeRuntime([_progress("청크1"), _progress("청크2"), _terminal("완료")])
    service = StreamingEngineService(
        runtime_factory=lambda app_id: runtime,
        b14_service_bound=True,
        idempotency_adapter=adapter,
    )

    prepared = await service.prepare(
        method="POST",
        path=STREAM_PATH,
        content_type="application/json",
        body=json.dumps(_payload(key="key-disconnect-1")).encode(),
    )
    assert isinstance(prepared, PreparedStream)

    gen = service.iter_ndjson(prepared)
    first_line = await anext(gen)
    assert "청크1" in first_line

    # Consumer disconnects: close the async generator
    await gen.aclose()

    assert len(adapter.complete_calls) == 0
    assert len(adapter.abort_calls) == 1
    assert adapter.abort_calls[0]["idempotency_key"] == "key-disconnect-1"


@pytest.mark.asyncio
async def test_streaming_iterator_exhaustion_without_done_triggers_abort() -> None:
    # (h) done 없는 이터레이터 소진 -> abort 1회.
    adapter = _InMemoryIdempotencyAdapter()
    runtime = _FakeRuntime([_progress("미완료청크")])
    service = StreamingEngineService(
        runtime_factory=lambda app_id: runtime,
        b14_service_bound=True,
        idempotency_adapter=adapter,
    )

    prepared = await service.prepare(
        method="POST",
        path=STREAM_PATH,
        content_type="application/json",
        body=json.dumps(_payload(key="key-incomplete-1")).encode(),
    )
    assert isinstance(prepared, PreparedStream)

    lines = [line async for line in service.iter_ndjson(prepared)]
    assert len(lines) == 1  # Only progress emitted, iterator finished without done=True

    assert len(adapter.complete_calls) == 0
    assert len(adapter.abort_calls) == 1
    assert adapter.abort_calls[0]["idempotency_key"] == "key-incomplete-1"
