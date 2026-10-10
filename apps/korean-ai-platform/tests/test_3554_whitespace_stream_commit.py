"""#3554: whitespace is not visible B14 output and cannot commit HTTP/SSE.

Network-free, real TestClient -> auto-stream gateway -> streaming router ->
platform adapter -> httpx.MockTransport; no credential/Provider access.
The legacy auto-preview route is test-only here; this does not authorize
automatic model selection or provider fallback for customer products.
"""
from __future__ import annotations

import json

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.b14_runtime_config import runtime_config as rcfg

URL = "/api/pilot/v1/chat/completions/auto-stream-preview"
UPSTREAM = "agnes-3.0-flash"


@pytest.fixture
def live_fake_provider(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv("PADIEM_AGNES_API_KEY", "sk-local-mock-only-3554-123456789")
    monkeypatch.delenv("PADIEM_POOLSIDE_API_KEY", raising=False)
    old_mode, old_key = rcfg.provider_mode, rcfg.api_key
    rcfg.provider_mode = "live"
    rcfg.api_key = "offline-test-gateway-3554"
    try:
        yield
    finally:
        rcfg.provider_mode = old_mode
        rcfg.api_key = old_key


def _request():
    return {
        "model": "b14/auto",
        "messages": [{"role": "user", "content": "synthetic whitespace only"}],
        "stream": True,
        "business14": {
            "task_type": "general",
            "required_capabilities": ["free"],
            "allow_external_fallback": False,
            "max_attempts": 1,
        },
    }


def _frame(content, *, finish=None):
    data = {
        "id": "offline-3554",
        "model": UPSTREAM,
        "choices": [{
            "index": 0,
            "delta": {"content": content} if content is not None else {},
            "finish_reason": finish,
        }],
    }
    return "data: " + json.dumps(data, ensure_ascii=False) + "\n\n"


def _run(wire):
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        body = json.loads(request.content)
        calls.append(body["model"])
        assert body["messages"] == _request()["messages"]
        assert body["stream"] is True
        assert "temperature" not in body
        assert "max_tokens" not in body
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=wire.encode("utf-8"),
        )

    app = create_app()
    app.state.stream_transport = httpx.MockTransport(respond)
    with TestClient(app) as client:
        result = client.post(URL, json=_request())
    assert calls == [UPSTREAM], "never retry or silently change model"
    return result


@pytest.mark.usefixtures("live_fake_provider")
@pytest.mark.parametrize("whitespace", [" ", " \t\n ", "\r\n", "\u3000"])
def test_whitespace_only_done_is_http_502_before_sse_starts(whitespace):
    wire = _frame(whitespace) + _frame(None, finish="length") + "data: [DONE]\n\n"
    response = _run(wire)

    assert response.status_code == 502
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == "empty_stream_answer"
    assert "data: [DONE]" not in response.text
    assert "event: error" not in response.text


@pytest.mark.usefixtures("live_fake_provider")
def test_whitespace_is_buffered_until_first_real_text_then_sse_200():
    wire = (
        _frame(" \n\t")
        + _frame("정상 출력")
        + _frame(None, finish="stop")
        + "data: [DONE]\n\n"
    )
    response = _run(wire)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    frames = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]
    text_events = [
        frame for frame in frames
        if frame["choices"] and "content" in frame["choices"][0]["delta"]
    ]
    assert [event["choices"][0]["delta"]["content"] for event in text_events] == [
        " \n\t", "정상 출력"
    ]
    assert text_events[0]["business14"]["committed"] is False
    assert text_events[1]["business14"]["committed"] is True
    assert response.text.count("data: [DONE]") == 1
    assert "event: error" not in response.text
