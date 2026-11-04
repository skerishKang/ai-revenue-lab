"""#6812: one bounded metrics line per /api/orchestration turn.

The line carries counts only — tier, whether web search ran, evidence count and
total snippet characters, the characters handed to B14, history turns, B14
attempts, first-byte time and the result code. No prompt, answer, path or
account value may enter it, and no new limit or block is introduced.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import request_telemetry as rt
from app.orchestration_routes import (
    _b14_input_chars,
    _conversation_hash,
    _stream_turn_summary,
    _turn_metrics,
)


def test_input_chars_count_history_and_system_context():
    messages = [
        {"role": "user", "content": "안녕"},
        {"role": "assistant", "content": "네"},
    ]
    assert _b14_input_chars(messages, None) == 3
    assert _b14_input_chars(messages, "근거") == 5
    assert _b14_input_chars([], "") == 0


def test_conversation_hash_is_eight_hex_and_never_the_id():
    hashed = _conversation_hash("conv_1234567890")
    assert hashed is not None and len(hashed) == 8
    assert all(character in "0123456789abcdef" for character in hashed)
    assert hashed == _conversation_hash("conv_1234567890")
    assert hashed != _conversation_hash("conv_1234567891")
    assert _conversation_hash(None) is None
    assert _conversation_hash("") is None


def test_turn_metrics_are_created_once_per_request():
    request = SimpleNamespace(state=SimpleNamespace())
    first = _turn_metrics(request)
    first["evidence_count"] = 3
    assert _turn_metrics(request) is first
    assert request.state.orchestration_turn["evidence_count"] == 3


def test_turn_summary_keeps_only_bounded_numbers(monkeypatch):
    emitted: list[dict[str, object]] = []
    monkeypatch.setattr(rt, "default_emitter", emitted.append)
    token = rt._CURRENT_REQUEST_ID.set(rt.new_request_id())
    try:
        rt.emit_turn_summary(
            duration_ms=1234.5,
            code=None,
            metrics={
                "tier": "free",
                "conversation": "a1b2c3d4",
                "web_search": True,
                "evidence_count": 5,
                "evidence_chars": 12345,
                "input_chars": -7,
                "history_turns": 2 ** 40,
                "b14_attempts": None,
                "first_byte_ms": 2426.4,
                # A prompt or any free text must never survive the projection.
                "prompt": "사용자 원문입니다",
                "tier_text": "C:/Users/private",
            },
        )
    finally:
        rt._CURRENT_REQUEST_ID.reset(token)

    assert len(emitted) == 1
    event = emitted[0]
    assert event["event"] == "ai_stage"
    assert event["stage"] == "turn.summary"
    assert event["outcome"] == "ok"
    metrics = event["metrics"]
    assert metrics["tier"] == "free"
    assert metrics["conversation"] == "a1b2c3d4"
    assert metrics["web_search"] is True
    assert metrics["evidence_count"] == 5
    assert metrics["evidence_chars"] == 12345
    assert metrics["input_chars"] == 0  # negative is clamped, never trusted
    assert metrics["history_turns"] == 10 ** 9  # bounded
    assert metrics["b14_attempts"] is None
    assert metrics["first_byte_ms"] == 2426
    assert "prompt" not in metrics and "tier_text" not in metrics
    assert "사용자 원문입니다" not in str(event)


def test_turn_summary_is_silent_without_a_request_id(monkeypatch):
    emitted: list[dict[str, object]] = []
    monkeypatch.setattr(rt, "default_emitter", emitted.append)
    rt.emit_turn_summary(duration_ms=1.0, code=None, metrics={"tier": "free"})
    assert emitted == []


class _FakeResponse:
    def __init__(self, chunks, raises=False):
        self.body_iterator = self._body(chunks, raises)
        self.calls = 0

    async def _body(self, chunks, raises):
        self.calls += 1
        for chunk in chunks:
            yield chunk
        if raises:
            raise RuntimeError("upstream message is never logged")


class _FakeTiming:
    def elapsed_ms(self) -> float:
        return 42.0


@pytest.mark.asyncio
async def test_stream_summary_is_emitted_once_when_the_stream_ends(monkeypatch):
    captured: list[dict[str, object]] = []
    monkeypatch.setattr(
        rt, "emit_turn_summary",
        lambda **kwargs: captured.append(kwargs),
    )
    request = SimpleNamespace(state=SimpleNamespace(orchestration_turn={"tier": "free"}))
    response = _FakeResponse([b"a", b"b"])

    _stream_turn_summary(request, response, _FakeTiming())
    chunks = [chunk async for chunk in response.body_iterator]

    assert chunks == [b"a", b"b"]
    assert len(captured) == 1
    assert captured[0]["code"] is None
    assert captured[0]["metrics"]["tier"] == "free"
    assert captured[0]["duration_ms"] == 42.0


@pytest.mark.asyncio
async def test_stream_summary_records_a_failed_stream_without_its_message(monkeypatch):
    captured: list[dict[str, object]] = []
    monkeypatch.setattr(
        rt, "emit_turn_summary",
        lambda **kwargs: captured.append(kwargs),
    )
    request = SimpleNamespace(state=SimpleNamespace(orchestration_turn={"tier": "free"}))
    response = _FakeResponse([b"a"], raises=True)

    _stream_turn_summary(request, response, _FakeTiming())
    with pytest.raises(RuntimeError):
        [chunk async for chunk in response.body_iterator]

    assert len(captured) == 1
    assert captured[0]["code"] == "stream_error"
    assert "upstream message" not in str(captured[0])
