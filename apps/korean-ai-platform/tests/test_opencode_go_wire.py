"""Wire-protocol boundary tests; all outbound calls use synthetic MockTransport."""
import json

import httpx
import pytest

from app.pilot import opencode_go_wire as go
from app.pilot.errors import InvalidRequest, PilotNotConfigured, MalformedUpstreamResponse, UpstreamAuthFailed

SESSION = "conv_padiem_mock_00001"
TURNS = [{"role": "system", "content": "Code only"}, {"role": "user", "content": "Write a Python function."}]
GO_IDS = ["longcat-2.5-preview-free", "step-5-preview-free", "muse-spark-1.3-contributor", "gpt-6-luna", "claude-haiku-5-5"]


@pytest.mark.parametrize("name,wire", [
    ("longcat-2.5-preview-free", "chat/completions"),
    ("step-5-preview-free", "chat/completions"),
    ("muse-spark-1.3-contributor", "responses"),
    ("gpt-6-luna", "responses"),
    ("claude-haiku-5-5", "messages"),
])
def test_five_exact_wire_shapes(name, wire):
    url, body, h = go.prepare_go_request(
        model_id="opencode-go/" + name, upstream_model=name, messages=TURNS,
        session_id=SESSION, max_tokens=32, streaming=True,
    )
    assert url == wire
    assert body["model"] == name and body["stream"] is True
    assert h["x-opencode-session"] == SESSION
    assert h["User-Agent"] == "padiem-claw-coding-agent/1.0"
    assert ("input" in body) == (wire == "responses")
    assert ("system" in body) == (wire == "messages")
    if wire == "messages":
        assert h["anthropic-version"] == "2023-06-01"
        assert body["messages"] == [{"role": "user", "content": "Write a Python function."}]


@pytest.mark.parametrize("name", GO_IDS)
def test_missing_or_untrusted_session_fails_closed(name):
    with pytest.raises(InvalidRequest, match="stable conversation"):
        go.prepare_go_request(model_id="opencode-go/" + name, upstream_model=name, messages=TURNS, session_id=None, max_tokens=20)
    with pytest.raises(InvalidRequest):
        go.prepare_go_request(model_id="zanslab/" + name, upstream_model=name, messages=TURNS, session_id=SESSION, max_tokens=20)


def test_claude_budget_is_required_not_invented():
    with pytest.raises(InvalidRequest, match="explicit max_tokens"):
        go.prepare_go_request(model_id="opencode-go/claude-haiku-5-5", upstream_model="claude-haiku-5-5", messages=TURNS, session_id=SESSION)


@pytest.mark.parametrize("name,reply,expected", [
    ("longcat-2.5-preview-free", {"model": "longcat-2.5-preview-free", "choices": [{"message": {"content": "Hello"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 2, "completion_tokens": 1}}, "Hello"),
    ("gpt-6-luna", {"model": "gpt-6-luna", "status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": "Hello"}]}], "usage": {"input_tokens": 2, "output_tokens": 1}}, "Hello"),
    ("claude-haiku-5-5", {"model": "claude-haiku-5-5", "type": "message", "role": "assistant", "content": [{"type": "text", "text": "Hello"}], "usage": {"input_tokens": 2, "output_tokens": 1}}, "Hello"),
])
@pytest.mark.asyncio
async def test_completed_protocols_with_synthetic_headers(monkeypatch, name, reply, expected):
    monkeypatch.setattr(go, "_authorization_gate", lambda *_: None)
    async def synthetic_auth(h, wire):
        if wire == "messages":
            return {**h, "x-api-key": "synthetic-test-credential"}
        return {**h, "Authorization": "Bearer synthetic-test-credential"}
    monkeypatch.setattr(go, "_authenticated_headers", synthetic_auth)
    seen = []
    def handle(req):
        seen.append(req)
        assert req.url.host == "opencode.ai"
        assert req.headers["x-opencode-session"] == SESSION
        if name.startswith("claude"):
            assert req.url.path.endswith("/messages")
            assert req.headers["x-api-key"] == "synthetic-test-credential"
            assert "authorization" not in req.headers
        elif name.startswith("gpt"):
            assert req.url.path.endswith("/responses")
        else:
            assert req.url.path.endswith("/chat/completions")
        return httpx.Response(200, json=reply)
    got = await go.call_go_model(model_id="opencode-go/"+name, upstream_model=name, messages=TURNS, session_id=SESSION, max_tokens=32, transport=httpx.MockTransport(handle))
    assert got["choices"][0]["message"]["content"] == expected
    assert got["usage"] == {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_disabled_registry_never_sends_live_request():
    calls = []
    async def fail_if_called(h, wire):
        calls.append(1)
        raise AssertionError("Should not read a secret")
    original = go._authenticated_headers
    go._authenticated_headers = fail_if_called
    try:
        with pytest.raises(PilotNotConfigured):
            await go.call_go_model(model_id="opencode-go/gpt-6-luna", upstream_model="gpt-6-luna", messages=TURNS, session_id=SESSION, max_tokens=32, transport=httpx.MockTransport(lambda req: httpx.Response(200)))
    finally:
        go._authenticated_headers = original
    assert calls == []


@pytest.mark.parametrize("wire,name,payload", [
    ("chat/completions", "longcat-2.5-preview-free", {"choices": [{"message": {"content": ""}}]}),
    ("responses", "gpt-6-luna", {"status": "failed", "output": []}),
    ("messages", "claude-haiku-5-5", {"type": "error", "content": []}),
])
def test_malformed_or_empty_answer_rejected(wire, name, payload):
    from app.pilot.upstream_answer_contract import UpstreamEmptyAnswer
    with pytest.raises((MalformedUpstreamResponse, UpstreamEmptyAnswer)) as exc:
        go._normalize_go_answer(wire, name, payload, latency_ms=10, response_bytes=10)
    assert type(exc.value).__name__ in ("MalformedUpstreamResponse", "UpstreamEmptyAnswer")


def _frame(event, data):
    return ("event: "+event+"\\n"+"data: "+json.dumps(data)+"\\n\\n").replace("\\n", "\n")


@pytest.mark.parametrize("name,sse", [
    ("step-5-preview-free", 'data: {"choices":[{"delta":{"content":"Hi"},"finish_reason":null}]}\n\ndata: [DONE]\n\n'),
    ("muse-spark-1.3-contributor", _frame("response.output_text.delta", {"type":"response.output_text.delta","delta":"Hi"})+_frame("response.completed", {"type":"response.completed","response":{"status":"completed","usage":{"input_tokens":2,"output_tokens":1}}})),
    ("claude-haiku-5-5", _frame("content_block_delta", {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hi"}})+_frame("message_stop", {"type":"message_stop"})),
])
@pytest.mark.asyncio
async def test_three_stream_shapes(monkeypatch, name, sse):
    monkeypatch.setattr(go, "_authorization_gate", lambda *_: None)
    async def synthetic_auth(h, wire):
        return {**h, "x-api-key": "test-credential"} if wire == "messages" else {**h, "Authorization": "Bearer test-credential"}
    monkeypatch.setattr(go, "_authenticated_headers", synthetic_auth)
    events = [e async for e in go.stream_go_model(
        model_id="opencode-go/"+name, upstream_model=name, messages=TURNS,
        session_id=SESSION, max_tokens=32,
        transport=httpx.MockTransport(lambda req: httpx.Response(200, content=sse.encode(), headers={"Content-Type":"text/event-stream"})),
    )]
    assert "".join(e.delta_content or "" for e in events) == "Hi"
    assert events[-1].done is True


@pytest.mark.asyncio
async def test_upstream_auth_error_does_not_echo_body(monkeypatch):
    monkeypatch.setattr(go, "_authorization_gate", lambda *_: None)
    async def synthetic_auth(h, wire):
        return {**h, "Authorization": "Bearer synthetic-credential"}
    monkeypatch.setattr(go, "_authenticated_headers", synthetic_auth)
    with pytest.raises(UpstreamAuthFailed) as exc:
        await go.call_go_model(model_id="opencode-go/gpt-6-luna", upstream_model="gpt-6-luna", messages=TURNS, session_id=SESSION, max_tokens=32,
                               transport=httpx.MockTransport(lambda r: httpx.Response(401, text="private-provider-token-debug")))
    assert "private-provider-token-debug" not in str(exc.value)
