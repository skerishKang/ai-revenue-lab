"""답변 시간 예산 답변 시간 예산: 앞단 60초 안에서 Chat이 먼저 한국어로 끝난다."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.chat_pc_drive import CHAT_PC_QUERY_AGENT_ID
from app.orchestration_bridge import (
    ENGINE_TIMEOUT_MESSAGE,
    B62EngineOrchestrationBridge,
    B62OrchestrationError,
)
from app.orchestration_routes import (
    ANSWER_BUDGET_HEADER,
    MIN_ANSWER_BUDGET_MS,
    _answer_budget_seconds,
)
from app.orchestration_stream import ndjson_answer
from app.orchestration_timing import OrchestrationTiming


def _request(headers: dict[str, str] | None = None) -> Request:
    raw = [(b"content-type", b"application/json")]
    raw.extend((name.encode("latin-1"), value.encode("latin-1")) for name, value in (headers or {}).items())
    return Request({
        "type": "http", "method": "POST", "path": "/api/orchestration",
        "headers": raw, "query_string": b"",
    })


def _skill() -> SimpleNamespace:
    return SimpleNamespace(
        id="auto", title="Padiem Chat", description="request",
        system_instruction="identity", task_type="general",
        optimize_for="balanced", max_tokens=None,
    )


def test_remaining_budget_subtracts_elapsed_and_margin(monkeypatch):
    monkeypatch.setattr(OrchestrationTiming, "elapsed_ms", lambda self: 1_500.0)
    timing = OrchestrationTiming()
    value = _answer_budget_seconds(
        _request({ANSWER_BUDGET_HEADER: "60000"}), timing,
    )
    assert value == pytest.approx(50.5)


@pytest.mark.parametrize("raw", [None, "", "not-a-number", "999999999"])
def test_invalid_or_widened_budget_falls_back_to_the_front_ceiling(monkeypatch, raw):
    monkeypatch.setattr(OrchestrationTiming, "elapsed_ms", lambda self: 0.0)
    headers = {} if raw is None else {ANSWER_BUDGET_HEADER: raw}
    value = _answer_budget_seconds(_request(headers), OrchestrationTiming())
    assert value == pytest.approx(52.0)


def test_spent_budget_never_drops_below_the_engine_minimum(monkeypatch):
    monkeypatch.setattr(OrchestrationTiming, "elapsed_ms", lambda self: 59_500.0)
    value = _answer_budget_seconds(
        _request({ANSWER_BUDGET_HEADER: "60000"}), OrchestrationTiming(),
    )
    assert value == pytest.approx(MIN_ANSWER_BUDGET_MS / 1000.0)


def test_engine_request_carries_the_budget_and_clamps_it():
    request = B62EngineOrchestrationBridge.build_engine_request(
        user_id="user_1", messages=[{"role": "user", "content": "hi"}],
        skill=_skill(), model_id="free-model", conversation_id=None,
        timeout_seconds=50.5,
    )
    assert request["execution_context"]["timeout_seconds"] == pytest.approx(50.5)

    tiny = B62EngineOrchestrationBridge.build_engine_request(
        user_id="user_1", messages=[{"role": "user", "content": "hi"}],
        skill=_skill(), model_id="free-model", conversation_id=None,
        timeout_seconds=0.2,
    )
    assert tiny["execution_context"]["timeout_seconds"] == 1.0

    huge = B62EngineOrchestrationBridge.build_engine_request(
        user_id="user_1", messages=[{"role": "user", "content": "hi"}],
        skill=_skill(), model_id="free-model", conversation_id=None,
        timeout_seconds=99_999,
    )
    assert huge["execution_context"]["timeout_seconds"] == 3600.0


def test_absent_budget_keeps_the_existing_wire_shape():
    request = B62EngineOrchestrationBridge.build_engine_request(
        user_id="user_1", messages=[{"role": "user", "content": "hi"}],
        skill=_skill(), model_id="free-model", conversation_id=None,
    )
    assert "timeout_seconds" not in request["execution_context"]


def test_pc_tool_turn_keeps_no_execution_deadline():
    request = B62EngineOrchestrationBridge.build_engine_request(
        user_id="user_1", messages=[{"role": "user", "content": "hi"}],
        skill=_skill(), model_id="free-model", conversation_id=None,
        agent_plan={"agent_id": CHAT_PC_QUERY_AGENT_ID},
        timeout_seconds=50.5,
    )
    assert request["execution_context"]["timeout_seconds"] is None


def test_non_finite_budget_is_refused_instead_of_widening():
    with pytest.raises(B62OrchestrationError):
        B62EngineOrchestrationBridge.build_engine_request(
            user_id="user_1", messages=[{"role": "user", "content": "hi"}],
            skill=_skill(), model_id="free-model", conversation_id=None,
            timeout_seconds=float("nan"),
        )


def test_timeout_copy_is_the_existing_korean_answer():
    assert ENGINE_TIMEOUT_MESSAGE == "AI 응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요."


class _StalledBridge:
    def __init__(self) -> None:
        self.buffered = 0
        self.closed = False

    async def start_stream(self, **kwargs):
        try:
            await asyncio.sleep(10)
            yield {"result": None}
        finally:
            self.closed = True

    async def start(self, **kwargs):
        self.buffered += 1
        raise AssertionError("a spent budget must not retry the buffered path")


async def _collect_until_budget() -> tuple[list[dict], _StalledBridge]:
    bridge = _StalledBridge()
    frames = [
        json.loads(chunk.decode("utf-8"))
        async for chunk in ndjson_answer(
            bridge=bridge,
            stream_kwargs={},
            buffered_kwargs={},
            timing=OrchestrationTiming(),
            on_completed=lambda result: {},
            timeout_seconds=0.05,
        )
    ]
    return frames, bridge


def test_ndjson_stream_ends_with_upstream_timeout_when_budget_is_spent():
    frames, bridge = asyncio.run(_collect_until_budget())
    assert frames[0] == {"type": "meta", "stream": True}
    assert frames[-1] == {"type": "error", "code": "upstream_timeout"}
    assert bridge.buffered == 0
    assert bridge.closed is True
