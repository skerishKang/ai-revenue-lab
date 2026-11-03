"""#6742 일반 답변 NDJSON 스트리밍: 줄 순서·done 1회·대체·중단 시 저장 정책."""
from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace

from app.orchestration_stream import (
    HEARTBEAT_MIN_INTERVAL_SECONDS,
    PC_PROGRESS_STAGES,
    PROGRESS_EVENT_KINDS,
    PROGRESS_KINDS,
    ProgressFrameBuilder,
    line,
    ndjson_answer,
    orchestration_stream_enabled,
    wants_ndjson,
)
from app.orchestration_timing import OrchestrationTiming


class _Result:
    def __init__(self, answer: str | None, conversation_id: str | None = "chat_1") -> None:
        self.answer = answer
        self.conversation_id = conversation_id
        self.orchestration = {"events": [], "answer": answer}
        self.user_text = "안녕"


class _Bridge:
    def __init__(self, records=None, *, fail=False, answer="완성 답변") -> None:
        self.records = records or []
        self.fail = fail
        self.answer = answer
        self.started = 0
        self.buffered = 0
        self.saved = 0

    async def start_stream(self, **kwargs):
        if self.fail:
            raise RuntimeError("engine stream unavailable")
        for record in self.records:
            yield record

    async def start(self, **kwargs):
        self.buffered += 1
        return _Result(self.answer)

    async def completed(self, result):
        self.saved += 1
        return {"conversation_id": result.conversation_id, "message_id": result.conversation_id, "usage": None}


async def _collect(bridge, timing=None):
    timing = timing or OrchestrationTiming()
    chunks = [
        chunk async for chunk in ndjson_answer(
            bridge=bridge,
            stream_kwargs={},
            buffered_kwargs={},
            timing=timing,
            on_completed=bridge.completed,
        )
    ]
    return [json.loads(chunk.decode("utf-8")) for chunk in chunks], timing


def test_flag_and_request_detection():
    assert orchestration_stream_enabled({"PADIEM_CHAT_ORCHESTRATION_STREAM": "1"}) is True
    assert orchestration_stream_enabled({"PADIEM_CHAT_ORCHESTRATION_STREAM": "true"}) is True
    assert orchestration_stream_enabled({"PADIEM_CHAT_ORCHESTRATION_STREAM": "off"}) is False
    assert orchestration_stream_enabled({}) is False

    assert wants_ndjson({"stream": 1}, None) is True
    assert wants_ndjson({"stream": "true"}, None) is True
    assert wants_ndjson({}, "application/x-ndjson") is True
    assert wants_ndjson({}, "application/json") is False
    assert wants_ndjson({"stream": 0}, None) is False


def test_lines_are_one_json_object_each():
    encoded = line({"type": "delta", "text": "안"})
    assert encoded.endswith(b"\n")
    assert json.loads(encoded.decode("utf-8")) == {"type": "delta", "text": "안"}


def test_progress_projection_is_allowlisted_and_drops_private_engine_fields():
    builder = ProgressFrameBuilder(clock=lambda: 0.0)
    records = [
        {"event": {"event_id": "event-secret", "run_id": "run-secret", "trace_id": "trace-secret",
                    "app_id": "internal-app", "kind": "run_started", "sequence": 1,
                    "timestamp_iso": "2026-11-04T00:00:00Z", "message": "raw prompt secret",
                    "metadata": {"path": "C:\\secret\\file.txt"}}},
        {"event": {"kind": "context_prepared", "message": "raw prompt"}},
        {"event": {"kind": "plan_created", "metadata": {"tenant_id": "tenant-secret"}}},
        {"event": {"kind": "tool_started", "message": "raw message",
                    "metadata": {"tool_id": "web_search", "secret": "hidden"}}},
        {"event": {"kind": "tool_completed", "metadata": {"tool_id": "claw.pc.read_file"}}},
        {"event": {"kind": "tool_failed", "metadata": {"tool_id": "unknown-tool-name"}}},
        {"pc_progress": {"pc_run_id": "pc-secret", "dispatch_id": "dispatch-secret",
                          "kind": "read", "stage": "executing", "sequence": 9, "elapsed_ms": 1200}},
        {"heartbeat": {"run_id": "run-secret", "trace_id": "trace-secret", "elapsed_ms": 5000}},
        {"event": {"kind": "memory_read", "message": "not in allowlist"}},
        {"pc_progress": {"stage": "untrusted-stage", "elapsed_ms": 1}},
    ]
    frames = [frame for record in records if (frame := builder.from_engine_record(record))]

    assert PROGRESS_EVENT_KINDS == {
        "run_started", "context_prepared", "plan_created", "tool_started", "tool_completed", "tool_failed",
    }
    assert PROGRESS_KINDS == PROGRESS_EVENT_KINDS | {"pc_progress", "heartbeat"}
    assert PC_PROGRESS_STAGES == {"accepted", "picked_up", "executing", "result"}
    assert HEARTBEAT_MIN_INTERVAL_SECONDS == 5.0
    assert [frame["kind"] for frame in frames] == [
        "run_started", "context_prepared", "plan_created", "tool_started", "tool_completed",
        "tool_failed", "pc_progress", "heartbeat",
    ]
    assert frames[0] == {
        "type": "progress", "kind": "run_started", "sequence": 1, "label": "질문 확인 중",
    }
    assert frames[3]["label"] == "웹 확인 중"
    assert frames[4]["label"] == "PC 작업 완료"
    assert frames[5]["label"] == "도구 작업 확인이 필요해요"
    assert frames[6] == {
        "type": "progress", "kind": "pc_progress", "sequence": 7, "label": "PC 작업 중",
        "stage": "executing", "elapsed_ms": 1200,
    }
    assert all(set(frame) <= {"type", "kind", "stage", "sequence", "elapsed_ms", "label"} for frame in frames)
    serialized = json.dumps(frames, ensure_ascii=False)
    for private_value in (
        "event-secret", "run-secret", "trace-secret", "internal-app", "tenant-secret",
        "pc-secret", "dispatch-secret", "raw prompt", "raw message", "unknown-tool-name",
    ):
        assert private_value not in serialized


def test_heartbeat_projection_is_rate_limited_to_five_seconds():
    ticks = iter([10.0, 14.99, 15.0])
    builder = ProgressFrameBuilder(clock=lambda: next(ticks))
    heartbeat = {"heartbeat": {"run_id": "private", "trace_id": "private", "elapsed_ms": 10000}}

    first = builder.from_engine_record(heartbeat)
    suppressed = builder.from_engine_record(heartbeat)
    second = builder.from_engine_record(heartbeat)

    assert first == {"type": "progress", "kind": "heartbeat", "sequence": 1,
                    "label": "작업 진행 중", "elapsed_ms": 10000}
    assert suppressed is None
    assert second["sequence"] == 2


def test_ndjson_answer_forwards_sanitized_progress_before_deltas_and_done():
    bridge = _Bridge(records=[
        {"event": {"kind": "run_started", "message": "raw prompt", "run_id": "private-run"}},
        {"event": {"kind": "context_prepared", "metadata": {"trace_id": "private-trace"}}},
        {"event": {"kind": "plan_created"}},
        {"event": {"kind": "tool_started", "metadata": {"tool_id": "web_search"}}},
        {"pc_progress": {"pc_run_id": "private-pc", "dispatch_id": "private-dispatch",
                          "kind": "read", "stage": "accepted", "sequence": 1, "elapsed_ms": 12}},
        {"pc_progress": {"pc_run_id": "private-pc", "dispatch_id": "private-dispatch",
                          "kind": "read", "stage": "executing", "sequence": 2, "elapsed_ms": 98}},
        {"heartbeat": {"run_id": "private-run", "trace_id": "private-trace", "elapsed_ms": 5000}},
        {"event": {"kind": "tool_completed", "metadata": {"tool_id": "web_search"}}},
        {"event": {"kind": "run_completed", "message": "excluded terminal event"}},
        {"text_delta": {"delta": "final answer"}},
        {"result": _Result("final answer")},
    ])

    frames, _ = asyncio.run(_collect(bridge))

    assert [frame["type"] for frame in frames] == [
        "meta", "progress", "progress", "progress", "progress", "progress", "progress", "progress",
        "progress", "delta", "done",
    ]
    progress = [frame for frame in frames if frame["type"] == "progress"]
    assert [frame["kind"] for frame in progress] == [
        "run_started", "context_prepared", "plan_created", "tool_started", "pc_progress", "pc_progress",
        "heartbeat", "tool_completed",
    ]
    assert [frame["label"] for frame in progress] == [
        "질문 확인 중", "질문 확인 중", "답변 방향 확인", "웹 확인 중", "PC 요청 접수",
        "PC 작업 중", "작업 진행 중", "웹 확인 완료",
    ]
    serialized = json.dumps(frames, ensure_ascii=False)
    for private_value in ("raw prompt", "private-run", "private-trace", "private-pc", "private-dispatch"):
        assert private_value not in serialized
    assert bridge.saved == 1


def test_streamed_answer_is_meta_deltas_then_one_done_and_saves_once():
    bridge = _Bridge(records=[
        {"text_delta": {"delta": "안"}},
        {"text_delta": {"delta": "녕"}},
        {"result": _Result("안녕")},
    ])
    frames, timing = asyncio.run(_collect(bridge))
    assert [frame["type"] for frame in frames] == ["meta", "delta", "delta", "done"]
    assert [frame["text"] for frame in frames if frame["type"] == "delta"] == ["안", "녕"]
    assert frames[0]["stream"] is True
    assert frames[-1]["done"] is True
    assert frames[-1]["conversation_id"] == "chat_1"
    assert bridge.saved == 1, "저장은 done 직전에 정확히 한 번"
    assert bridge.buffered == 0, "스트림이 성공하면 완성 응답을 다시 부르지 않는다"
    assert "first_token_ms=" in timing.line()
    assert "first_token_ms=-1.0" not in timing.line()


def test_unavailable_stream_falls_back_to_one_buffered_delta():
    bridge = _Bridge(fail=True, answer="한 덩어리")
    frames, _ = asyncio.run(_collect(bridge))
    assert [frame["type"] for frame in frames] == ["meta", "delta", "done"]
    assert frames[1]["text"] == "한 덩어리"
    assert bridge.buffered == 1
    assert bridge.saved == 1


def test_engine_result_without_deltas_becomes_one_delta():
    bridge = _Bridge(records=[{"result": _Result("결과만")}])
    frames, _ = asyncio.run(_collect(bridge))
    assert [frame["type"] for frame in frames] == ["meta", "delta", "done"]
    assert frames[1]["text"] == "결과만"


def test_failure_after_first_delta_never_duplicates_the_answer():
    class _Broken(_Bridge):
        async def start_stream(self, **kwargs):
            yield {"text_delta": {"delta": "부분"}}
            raise RuntimeError("engine cut")

    bridge = _Broken()
    frames, _ = asyncio.run(_collect(bridge))
    assert [frame["type"] for frame in frames] == ["meta", "delta", "error"]
    assert frames[-1]["code"] == "invalid_engine_stream"
    assert bridge.buffered == 0, "첫 delta 뒤에는 완성 응답으로 다시 보내지 않는다"
    assert bridge.saved == 0


def test_empty_answer_is_an_error_not_a_done():
    bridge = _Bridge(records=[{"result": _Result("")}])
    frames, _ = asyncio.run(_collect(bridge))
    assert frames[-1] == {"type": "error", "code": "engine_execution_failed"}
    assert bridge.saved == 0


def test_disconnect_before_done_saves_nothing_but_still_logs_timing():
    records = []
    logger = logging.getLogger("padiem_chat.orchestration_timing")

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = Capture()
    logger.addHandler(handler)
    bridge = _Bridge(records=[{"text_delta": {"delta": "안"}}, {"result": _Result("안")}])

    async def consume_then_leave():
        generator = ndjson_answer(
            bridge=bridge, stream_kwargs={}, buffered_kwargs={},
            timing=OrchestrationTiming(), on_completed=bridge.completed,
        )
        first = await generator.__anext__()
        assert json.loads(first)["type"] == "meta"
        await generator.aclose()

    try:
        asyncio.run(consume_then_leave())
    finally:
        logger.removeHandler(handler)
    assert bridge.saved == 0, "끊긴 스트림은 저장하지 않는다"
    assert records and records[-1].getMessage().startswith("orchestration_timing_com2 ")
