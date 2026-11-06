"""#6907 2단계: thinking summary reaches the screen and never the answer.

Stage 1 (B14) streams a thinking fragment on its own wire field. These tests
pin the remaining contract: Chat projects it as its own event, the busier
JSON path never grows one, and neither the answer, the saved turn, the export
surface nor the privacy boundary ever contains thinking text.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import httpx

from padiem_ai_core.contracts import AgentProfile
from padiem_ai_core.execution_runtime import ExecutionRequest

from app.b14_client import B14Client, ChatStreamEvent, ChatToolCall
from app.byok_client import _anthropic_stream, _openai_stream
from app.config import Settings
import test_orchestration_stream_allowlist_261105 as allow
from test_chat_stream_ttfb_first_frame_261105 import (
    _app_with_client,
    _collect_simple,
    _payload,
)

STATIC = Path(__file__).resolve().parents[1] / "static"
MODEL_SENTINEL = "secret/free-model"


# ---------------------------------------------------------------------------
# Core -> Chat projection
# ---------------------------------------------------------------------------
class _ChunkStream(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = list(chunks)

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk


def _chunk(delta: dict, *, finish_reason=None) -> bytes:
    payload = {
        "id": "stream_thought_1",
        "object": "chat.completion.chunk",
        "model": MODEL_SENTINEL,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        "business14": {
            "request_id": "b14stream_thought_1",
            "route_mode": "manual",
            "selected_provider": "test-provider",
            "selected_model": MODEL_SENTINEL,
            "selected_upstream_model": MODEL_SENTINEL,
            "selected_route_id": "test:route",
            "fallback_used": False,
            "attempt_count": 1,
            "route_evidence_status": "live_streaming_preview",
        },
    }
    return b"data: " + json.dumps(payload).encode() + b"\n\n"


def _thought_sse() -> bytes:
    return (
        _chunk({"reasoning_content": "생각 "})
        + _chunk({"reasoning_content": "조각"})
        + _chunk({"content": "답"})
        + _chunk({}, finish_reason="stop")
        + b"data: [DONE]\n\n"
    )


def _execution_request() -> ExecutionRequest:
    return ExecutionRequest(
        agent=AgentProfile(
            id="general-agent",
            title="General",
            description="General streaming agent",
            system_instruction="Answer carefully.",
            task_type="general",
            optimize_for="korean",
            max_tokens=700,
            required_capabilities=("free",),
            model_policy={"model": MODEL_SENTINEL},
        ),
        messages=({"role": "user", "content": "안녕하세요"},),
        trace_id="trace-thought-1",
        session_id="session-thought-1",
    )


def test_core_projection_carries_thought_apart_from_the_answer():
    client = B14Client(
        Settings(runtime_mode="mock", b14_base_url="https://b14.test"),
        stream_transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=_ChunkStream([_thought_sse()]),
            )
        ),
    )

    async def collect():
        return [event async for event in client._stream_core(_execution_request())]

    events = asyncio.run(collect())

    assert [event.delta_thought for event in events] == ["생각 ", "조각", None, None]
    assert [event.delta_content for event in events] == [None, None, "답", None]
    assert events[-1].done is True


# ---------------------------------------------------------------------------
# /api/chat/stream (SSE) route
# ---------------------------------------------------------------------------
class _ThoughtStreamClient:
    def __init__(self):
        self.closed = False

    async def stream_text_auto(self, messages, *, skill=None, additional_system_context=None, **kwargs):
        try:
            yield ChatStreamEvent(delta_thought="생각")
            yield ChatStreamEvent(delta_content="답")
            yield ChatStreamEvent(done=True)
        finally:
            self.closed = True


def test_sse_shows_thought_before_the_answer_and_keeps_it_out_of_delta():
    client = _ThoughtStreamClient()
    app = _app_with_client(client)

    collected = asyncio.run(_collect_simple(app, _payload()))
    body = collected.body

    assert collected.status == 200
    assert body.index("event: thought") < body.index("event: delta") < body.index("event: done")
    thought = json.loads(body.split("event: thought\ndata: ", 1)[1].split("\n\n", 1)[0])
    delta = json.loads(body.split("event: delta\ndata: ", 1)[1].split("\n\n", 1)[0])
    assert thought == {"text": "생각"}
    assert delta == {"delta": "답"}
    assert MODEL_SENTINEL not in body
    assert client.closed is True


class _ThoughtAndToolStreamClient:
    async def stream_text_auto(self, messages, *, skill=None, additional_system_context=None, **kwargs):
        yield ChatStreamEvent(
            delta_thought="도구를 준비합니다.",
            tool_call=ChatToolCall(id="private-tool-call", name="untrusted", arguments={}),
        )


def test_sse_keeps_thought_when_the_same_stream_event_requests_a_tool():
    app = _app_with_client(_ThoughtAndToolStreamClient())

    collected = asyncio.run(_collect_simple(app, _payload()))
    body = collected.body

    assert collected.status == 200
    assert body.index("event: thought") < body.index("event: error")
    assert "도구를 준비합니다." in body
    assert "private-tool-call" not in body


# ---------------------------------------------------------------------------
# NDJSON orchestration route
# ---------------------------------------------------------------------------
class _ThoughtBridge:
    ready = True

    def __init__(self):
        self.started = 0
        self.streamed = 0

    async def start(self, **kwargs):
        self.started += 1
        return SimpleNamespace(
            answer="답",
            orchestration={"events": [], "answer": "답"},
            decision_status=None,
            conversation_id="chat_json",
            user_text=kwargs.get("user_text"),
        )

    async def start_stream(self, **kwargs):
        self.streamed += 1
        yield {"thought_delta": {"delta": "생각"}}
        yield {"text_delta": {"delta": "답"}}
        yield {
            "result": SimpleNamespace(
                answer="답",
                orchestration={"events": [], "answer": "답"},
                decision_status=None,
                conversation_id="chat_stream",
                user_text=kwargs.get("user_text"),
            )
        }


def test_stream_off_keeps_the_json_path_and_never_shows_thought(monkeypatch):
    monkeypatch.setattr(allow, "_Bridge", _ThoughtBridge)
    allow._install(monkeypatch, allow.USER)

    response = allow._call(
        allow._request(uid=allow.USER, stream_enabled=False, accept="application/x-ndjson")
    )

    assert response.status_code == 200
    assert response.media_type == "application/json"
    body = json.loads(response.body)
    assert body["answer"] == "답"
    assert "생각" not in response.body.decode("utf-8")
    assert "thought" not in response.body.decode("utf-8")


def test_stream_on_carries_thought_as_its_own_frame_and_saves_the_clean_answer(monkeypatch):
    monkeypatch.setattr(allow, "_Bridge", _ThoughtBridge)
    allow._install(monkeypatch, allow.USER)

    response = allow._call(
        allow._request(uid=allow.USER, stream_enabled=True, accept="application/x-ndjson")
    )

    assert response.media_type == "application/x-ndjson"
    frames = allow._ndjson_frames(response.body)
    assert [frame["type"] for frame in frames] == ["meta", "thought", "delta", "done"]
    assert frames[1] == {"type": "thought", "text": "생각"}
    assert frames[2] == {"type": "delta", "text": "답"}
    assert "생각" not in json.dumps(frames[-1], ensure_ascii=False)


# ---------------------------------------------------------------------------
# Browser contract
# ---------------------------------------------------------------------------
def test_ui_mounts_an_incremental_thinking_panel_outside_the_answer():
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    transport = (STATIC / "chat-transport.js").read_text(encoding="utf-8")
    locale = (STATIC / "locale.js").read_text(encoding="utf-8")
    css = (STATIC / "capability-presentation.css").read_text(encoding="utf-8")
    export = (STATIC / "conversation-export.js").read_text(encoding="utf-8")

    index = (STATIC / "index.html").read_text(encoding="utf-8")
    panel = (STATIC / "thought-panel.js").read_text(encoding="utf-8")

    assert "window.PadiemChatThoughtPanel.handleFrame(article, frame" in app
    assert "window.PadiemChatThoughtPanel.settle(" in app
    assert "body.insertBefore(details, content)" in panel
    assert "details.open = true;" not in panel
    assert "details.open = false;" in panel
    assert 'return normalizeStreamFrame({ event: data.type, data: text });' in transport
    assert 'data.thought_delta' in transport
    assert '"orchestration-thinking-label": "생각 중…"' in locale
    assert '"orchestration-thinking-done-label": "생각 과정 보기"' in locale
    assert '<script src="./thought-panel.js"></script>' in index
    assert index.index('<script src="./thought-panel.js"></script>') < index.index('<script src="./app.js"></script>')
    assert ".orchestration-thought-summary > summary" in css
    # Done when the panel sits before .assistant-content and the exporter only
    # reads .assistant-content: thinking text cannot reach an export.
    assert 'article.querySelector(".assistant-content")' in export
    assert ".orchestration-thought-summary" not in export


def test_thought_frames_are_redacted_and_bounded_like_the_legacy_summary():
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    panel = (STATIC / "thought-panel.js").read_text(encoding="utf-8")

    assert "sanitize: safeThoughtSummary" in app
    assert "paragraph.textContent = sanitize(state.text);" in panel
    assert 'value.trim().slice(0, 2000)' in app
    assert "[user prompt omitted]" in app
    assert "[secret redacted]" in app


# ---------------------------------------------------------------------------
# Models without thinking summaries and BYOK wires
# ---------------------------------------------------------------------------
class _NoThoughtStreamClient:
    async def stream_text_auto(self, messages, *, skill=None, additional_system_context=None, **kwargs):
        yield ChatStreamEvent(delta_content="답")
        yield ChatStreamEvent(done=True)


def test_a_model_without_a_thinking_summary_renders_no_panel():
    collected = asyncio.run(_collect_simple(_app_with_client(_NoThoughtStreamClient()), _payload()))
    body = collected.body

    assert "event: thought" not in body
    assert "event: thought_summary" not in body
    assert "event: delta" in body


class _FakeSseResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    async def aiter_bytes(self):
        yield self.payload


def test_openai_wire_keeps_reasoning_content_apart_from_the_answer():
    raw = b"".join([
        b'data: {"model":"m","choices":[{"delta":{"reasoning_content":"\xec\x83\x9d\xea\xb0\x81"}}]}\n\n',
        b'data: {"model":"m","choices":[{"delta":{"content":"\xeb\x8b\xb5"},"finish_reason":"stop"}]}\n\n',
        b"data: [DONE]\n\n",
    ])

    result = asyncio.run(_openai_stream(_FakeSseResponse(raw), "m", enforce_model=True))

    assert result["answer"] == "답"
    assert result["thought"] == "생각"


def test_anthropic_wire_keeps_thinking_delta_apart_from_the_answer():
    raw = b"".join([
        b'data: {"type":"message_start","message":{"usage":{"input_tokens":1}}}\n\n',
        b'data: {"type":"content_block_start","content_block":{"type":"thinking","thinking":""}}\n\n',
        b'data: {"type":"content_block_delta","delta":{"type":"thinking_delta","thinking":"\xec\x83\x9d\xea\xb0\x81"}}\n\n',
        b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"\xeb\x8b\xb5"}}\n\n',
        b'data: {"type":"message_stop"}\n\n',
    ])

    result = asyncio.run(_anthropic_stream(_FakeSseResponse(raw)))

    assert result["answer"] == "답"
    assert result["thought"] == "생각"


def test_answer_accumulators_only_accept_answer_deltas():
    routes_source = (Path(__file__).resolve().parents[1] / "app" / "chat_routes.py").read_text(encoding="utf-8")
    orchestration_source = (Path(__file__).resolve().parents[1] / "app" / "orchestration_routes.py").read_text(encoding="utf-8")

    assert "answer_parts.append(event.delta_content)" in routes_source
    assert "answer_parts.append(event.delta_thought" not in routes_source
    assert "parts.append(event.delta_content)" in orchestration_source
    assert "parts.append(event.delta_thought" not in orchestration_source
