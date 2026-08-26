from __future__ import annotations

import json

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.errors import (
    MalformedUpstreamResponse,
    PilotNotConfigured,
    UpstreamAuthFailed,
    UpstreamClientError,
    UpstreamRateLimited,
    UpstreamResponseTooLarge,
    UpstreamServerError,
)
from app.pilot.openrouter_config import openrouter_config as orcfg
from app.pilot.openrouter_stream import (
    OpenRouterStreamEvent,
    stream_openrouter_chat_completions,
)


class FragmentedStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]):
        self.chunks = chunks
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_openrouter_config():
    saved = {
        "api_key": orcfg.api_key,
        "provider_mode": orcfg.provider_mode,
        "base_url": orcfg.base_url,
        "max_response_bytes": orcfg.max_response_bytes,
    }
    orcfg.api_key = ""
    orcfg.provider_mode = "mock"
    orcfg.base_url = "https://openrouter.ai/api/v1"
    orcfg.max_response_bytes = 1024 * 1024
    yield
    orcfg.api_key = saved["api_key"]
    orcfg.provider_mode = saved["provider_mode"]
    orcfg.base_url = saved["base_url"]
    orcfg.max_response_bytes = saved["max_response_bytes"]


def _set_live() -> str:
    key = "sk-or-v1-stream-secret-1234567890abcdef"
    orcfg.api_key = key
    orcfg.provider_mode = "live"
    return key


async def _collect(*, transport=None, model_id="openrouter/free", upstream_model="openrouter/free"):
    return [
        event
        async for event in stream_openrouter_chat_completions(
            messages=[{"role": "user", "content": "안녕하세요"}],
            temperature=0.2,
            max_tokens=64,
            model_id=model_id,
            upstream_model=upstream_model,
            provider="OpenRouter",
            transport=transport,
        )
    ]


@pytest.mark.asyncio
async def test_mock_stream_is_deterministic_and_zero_network():
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        raise AssertionError("mock mode must not call upstream")

    first = await _collect(transport=httpx.MockTransport(handler))
    second = await _collect(transport=httpx.MockTransport(handler))

    assert calls == 0
    assert first == second
    assert first[-1] == OpenRouterStreamEvent(done=True)
    assert first[0].delta_content is not None
    assert "Mock" in first[0].delta_content
    assert first[1].usage is not None
    assert first[1].usage.total_tokens == 0


@pytest.mark.asyncio
async def test_live_stream_parses_fragmented_lf_crlf_usage_done_and_free_policy():
    key = _set_live()
    captured = {}
    stream = FragmentedStream([])

    async def handler(request):
        captured["authorization"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content)
        payload = (
            b": keepalive\r\n\r\n"
            b"event: message\r\nid: ignored\r\n"
            b'data: {"id":"stream-1","model":"openrouter/free","choices":[{"delta":{"content":"\\uc548"},"finish_reason":null}]}\r\n\r\n'
            b'data: {"id":"stream-1","model":"openrouter/free","choices":[{"delta":{"content":"\\ub155"},"finish_reason":null}]}\n\n'
            b'data: {"id":"stream-1","model":"openrouter/free","choices":[{"delta":{},"finish_reason":"stop"}]}\r\n\r\n'
            b'data: {"id":"stream-1","model":"openrouter/free","choices":[],"usage":{"prompt_tokens":3,"completion_tokens":2,"total_tokens":5}}\n\n'
            b"data: [DONE]\r\n\r\n"
            b"data: this-must-not-be-read\n\n"
        )
        split_points = [5, 19, 41, 77, 121, 173, 251, 337, 419]
        pieces = []
        start = 0
        for end in split_points:
            pieces.append(payload[start:end])
            start = end
        pieces.append(payload[start:])
        stream.chunks = pieces
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=stream,
        )

    events = await _collect(transport=httpx.MockTransport(handler))

    assert captured["authorization"] == f"Bearer {key}"
    assert captured["body"]["stream"] is True
    assert captured["body"]["model"] == "openrouter/free"
    assert captured["body"]["provider"] == {
        "max_price": {"prompt": 0, "completion": 0}
    }
    assert [event.delta_content for event in events[:2]] == ["안", "녕"]
    assert events[2].finish_reason == "stop"
    assert events[3].usage is not None
    assert events[3].usage.total_tokens == 5
    assert events[4].done is True
    assert len(events) == 5
    assert stream.closed is True
    assert key not in repr(events)


@pytest.mark.asyncio
async def test_stream_without_done_fails_closed():
    _set_live()
    stream = FragmentedStream([
        b'data: {"id":"x","model":"m","choices":[{"delta":{"content":"a"},"finish_reason":null}]}\n\n'
    ])

    async def handler(request):
        return httpx.Response(200, stream=stream)

    with pytest.raises(MalformedUpstreamResponse):
        await _collect(transport=httpx.MockTransport(handler))
    assert stream.closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        b"data: not-json\n\n",
        b"data: []\n\n",
        b'data: {"choices":{}}\n\n',
        b'data: {"choices":[{"delta":"bad"}]}\n\n',
        b'data: {"choices":[{"delta":{"content":3}}]}\n\n',
        b'data: {"choices":[],"usage":{"total_tokens":-1}}\n\n',
    ],
)
async def test_malformed_stream_payloads_fail_closed(payload):
    _set_live()

    async def handler(request):
        return httpx.Response(200, stream=FragmentedStream([payload]))

    with pytest.raises(MalformedUpstreamResponse):
        await _collect(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_malformed_utf8_fails_closed():
    _set_live()

    async def handler(request):
        return httpx.Response(200, stream=FragmentedStream([b"data: \xff\n\n"]))

    with pytest.raises(MalformedUpstreamResponse):
        await _collect(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_stream_byte_cap_aborts_before_unbounded_buffering():
    _set_live()
    orcfg.max_response_bytes = 48
    stream = FragmentedStream([b"x" * 32, b"y" * 32])

    async def handler(request):
        return httpx.Response(200, stream=stream)

    with pytest.raises(UpstreamResponseTooLarge) as exc_info:
        await _collect(transport=httpx.MockTransport(handler))
    assert exc_info.value.max_bytes == 48
    assert stream.closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, UpstreamAuthFailed),
        (403, UpstreamAuthFailed),
        (429, UpstreamRateLimited),
        (500, UpstreamServerError),
        (503, UpstreamServerError),
        (400, MalformedUpstreamResponse),
        (404, UpstreamClientError),
        (422, UpstreamClientError),
    ],
)
async def test_stream_http_errors_match_existing_b14_contract(status, expected):
    _set_live()

    async def handler(request):
        return httpx.Response(status, content=b"bounded upstream error")

    with pytest.raises(expected):
        await _collect(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_redirect_is_not_followed():
    _set_live()
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(
            302,
            headers={"location": "https://openrouter.ai/api/v1/redirected"},
        )

    with pytest.raises(UpstreamClientError):
        await _collect(transport=httpx.MockTransport(handler))
    assert calls == 1


@pytest.mark.asyncio
async def test_live_missing_key_fails_before_network():
    orcfg.provider_mode = "live"
    orcfg.api_key = ""
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        raise AssertionError("missing key must fail before network")

    with pytest.raises(PilotNotConfigured):
        await _collect(transport=httpx.MockTransport(handler))
    assert calls == 0


@pytest.mark.asyncio
async def test_invalid_openrouter_base_url_fails_before_network():
    _set_live()
    orcfg.base_url = "https://openrouter.ai.evil.example/api/v1"
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        raise AssertionError("invalid host must fail before network")

    with pytest.raises(PilotNotConfigured):
        await _collect(transport=httpx.MockTransport(handler))
    assert calls == 0


def test_public_gateway_still_rejects_stream_true():
    client = TestClient(create_app())
    response = client.post(
        "/api/pilot/v1/chat/completions",
        json={
            "model": "b14/auto",
            "messages": [{"role": "user", "content": "안녕하세요"}],
            "stream": True,
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "stream_not_supported"
