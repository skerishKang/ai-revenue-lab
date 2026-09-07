from __future__ import annotations

import json

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.openrouter_config import openrouter_config as orcfg


STREAM_URL = "/api/pilot/v1/chat/completions/stream-preview"
CHAT_URL = "/api/pilot/v1/chat/completions"
MODEL = "kilo/nvidia-nemotron-3-ultra-550b-a55b-free"
MODEL_UPSTREAM = "nvidia/nemotron-3-ultra-550b-a55b:free"
LIVE_DUMMY_KEY = "unit-live-key-abcdef1234567890"


class _ChunkStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes], *, error_after: Exception | None = None):
        self.chunks = chunks
        self.error_after = error_after
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk
        if self.error_after is not None:
            raise self.error_after

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_openrouter_config(monkeypatch):
    monkeypatch.delenv("KILO_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("B14_PROVIDER_MODE", raising=False)
    saved = {
        "provider_mode": orcfg.provider_mode,
        "max_response_bytes": orcfg.max_response_bytes,
    }
    orcfg.provider_mode = "mock"
    orcfg.max_response_bytes = 1024 * 1024
    yield
    orcfg.provider_mode = saved["provider_mode"]
    orcfg.max_response_bytes = saved["max_response_bytes"]


def _payload(**overrides):
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "안녕하세요"}],
        "stream": True,
    }
    payload.update(overrides)
    return payload


def _client(transport: httpx.AsyncBaseTransport | None = None) -> TestClient:
    app = create_app()
    if transport is not None:
        app.state.openrouter_stream_transport = transport
    return TestClient(app)


def _json_data_frames(text: str) -> list[dict]:
    frames: list[dict] = []
    for line in text.splitlines():
        if not line.startswith("data: "):
            continue
        value = line[6:]
        if value == "[DONE]":
            continue
        frames.append(json.loads(value))
    return frames


def _valid_sse_chunks(content: str = "실제처럼 보이는 테스트") -> list[bytes]:
    first = {
        "id": "upstream_stream_1",
        "model": MODEL,
        "choices": [
            {
                "index": 0,
                "delta": {"content": content},
                "finish_reason": None,
            }
        ],
    }
    finish = {
        "id": "upstream_stream_1",
        "model": MODEL,
        "choices": [
            {
                "index": 0,
                "delta": {},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 3,
            "completion_tokens": 4,
            "total_tokens": 7,
        },
    }
    return [
        f"data: {json.dumps(first)}\n\n".encode(),
        f"data: {json.dumps(finish)}\n\n".encode(),
        b"data: [DONE]\n\n",
    ]


def test_mock_preview_is_sse_manual_route_with_done_and_metadata():
    client = _client()
    response = client.post(STREAM_URL, json=_payload())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache, no-store"
    assert "data: [DONE]" in response.text

    frames = _json_data_frames(response.text)
    assert frames
    first = frames[0]
    assert first["object"] == "chat.completion.chunk"
    assert first["choices"][0]["delta"]["content"].startswith("이것은 Mock 스트리밍 응답")
    metadata = first["business14"]
    assert metadata["route_mode"] == "manual"
    assert metadata["selected_model"] == MODEL
    assert metadata["fallback_allowed"] is False
    assert metadata["fallback_used"] is False
    assert metadata["attempt_count"] == 1
    assert metadata["provider_mode"] == "mock"
    assert metadata["route_evidence_status"] == "mock_no_upstream_call"


def test_existing_chat_endpoint_still_rejects_stream_true():
    client = _client()
    response = client.post(CHAT_URL, json=_payload())

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "stream_not_supported"


def test_preview_requires_stream_true():
    client = _client()
    payload = _payload()
    payload.pop("stream")
    response = client.post(STREAM_URL, json=payload)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


@pytest.mark.parametrize(
    "payload_update",
    [
        {"model": "b14/auto"},
        {"business14": {"allow_external_fallback": True}},
        {"business14": {"max_attempts": 2}},
    ],
)
def test_auto_or_fallback_streaming_is_rejected_before_network(payload_update):
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b"data: [DONE]\n\n")

    orcfg.provider_mode = "live"
    orcfg.api_key = LIVE_DUMMY_KEY
    client = _client(httpx.MockTransport(handler))
    response = client.post(STREAM_URL, json=_payload(**payload_update))

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "stream_not_supported"
    assert calls == 0


def test_legacy_non_catalog_route_is_rejected_before_network():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b"data: [DONE]\n\n")

    orcfg.provider_mode = "live"
    orcfg.api_key = LIVE_DUMMY_KEY
    client = _client(httpx.MockTransport(handler))
    response = client.post(STREAM_URL, json=_payload(model="legacy-provider-model"))

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_model"
    assert calls == 0


@pytest.mark.parametrize(
    ("upstream_status", "expected_status", "expected_code"),
    [
        (401, 401, "upstream_auth_failed"),
        (403, 401, "upstream_auth_failed"),
        # The Kilo Gateway route reports its own quota code for 429.
        (429, 429, "kilo_free_rate_limited"),
        (500, 502, "upstream_server_error"),
        (400, 502, "malformed_upstream_response"),
        (422, 502, "upstream_client_error"),
    ],
)
def test_pre_start_upstream_errors_keep_json_http_status(
    upstream_status: int,
    expected_status: int,
    expected_code: str,
):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(upstream_status, content=b"bounded error")

    orcfg.provider_mode = "live"
    orcfg.api_key = LIVE_DUMMY_KEY
    client = _client(httpx.MockTransport(handler))
    response = client.post(STREAM_URL, json=_payload())

    assert response.status_code == expected_status
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == expected_code


def test_malformed_first_event_fails_before_sse_200():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"data: not-json\n\n")

    orcfg.provider_mode = "live"
    orcfg.api_key = LIVE_DUMMY_KEY
    client = _client(httpx.MockTransport(handler))
    response = client.post(STREAM_URL, json=_payload())

    assert response.status_code == 502
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == "malformed_upstream_response"


def test_post_start_pilot_error_emits_bounded_error_event_without_done():
    first = _valid_sse_chunks("첫 토큰")[0]
    stream = _ChunkStream([first, b"data: not-json\n\n"])

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    orcfg.provider_mode = "live"
    orcfg.api_key = LIVE_DUMMY_KEY
    client = _client(httpx.MockTransport(handler))
    response = client.post(STREAM_URL, json=_payload())

    assert response.status_code == 200
    assert "첫 토큰" in response.text
    assert "event: error" in response.text
    assert '"code":"malformed_upstream_response"' in response.text
    assert '"after_stream_start":true' in response.text
    assert "data: [DONE]" not in response.text
    assert stream.closed is True


def test_post_start_unexpected_error_is_generic_and_secret_free():
    secret_marker = "DO-NOT-EXPOSE-SECRET-MARKER"
    first = _valid_sse_chunks("첫 토큰")[0]
    stream = _ChunkStream([first], error_after=RuntimeError(secret_marker))

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    orcfg.provider_mode = "live"
    orcfg.api_key = LIVE_DUMMY_KEY
    client = _client(httpx.MockTransport(handler))
    response = client.post(STREAM_URL, json=_payload())

    assert response.status_code == 200
    assert "event: error" in response.text
    assert '"code":"internal_error"' in response.text
    assert secret_marker not in response.text
    assert "data: [DONE]" not in response.text
    assert stream.closed is True


def test_live_preview_keyless_route_sends_no_key(monkeypatch):
    """Keyless Kilo route: no Authorization header, no key leakage.

    The Kilo provider spec is CredentialSource.NONE, so the legacy
    OpenRouter key plane is never forwarded to it.
    """
    stale_key = "unit-live-secret-abcdef1234567890"
    monkeypatch.setenv("KILO_API_KEY", stale_key)
    seen_authorization = None
    stream = _ChunkStream(_valid_sse_chunks("안전한 청크"))

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_authorization
        seen_authorization = request.headers.get("authorization")
        body = json.loads(request.content)
        assert body["stream"] is True
        assert body["model"] == MODEL_UPSTREAM
        return httpx.Response(200, stream=stream)

    orcfg.provider_mode = "live"
    orcfg.api_key = stale_key  # must stay on the OpenRouter plane
    client = _client(httpx.MockTransport(handler))
    response = client.post(STREAM_URL, json=_payload())

    assert response.status_code == 200
    assert seen_authorization is None
    assert stale_key not in response.text
    assert "안전한 청크" in response.text
    assert "data: [DONE]" in response.text


def test_live_preview_missing_key_is_anonymous_with_zero_key_material():
    """Keyless Kilo route: a missing key is not an error.

    Decision #1933 removed every secret-backed route, so the contract is
    "zero key material": exactly one anonymous call, no Authorization
    header, nothing returned to the client. The secret-required
    fail-closed path stays covered by
    test_platform_provider_credential_plane.py (Agnes).
    """
    calls = 0
    seen_authorization = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls, seen_authorization
        calls += 1
        seen_authorization = request.headers.get("authorization")
        return httpx.Response(200, stream=_ChunkStream(_valid_sse_chunks("익명 청크")))

    orcfg.provider_mode = "live"
    orcfg.api_key = ""
    client = _client(httpx.MockTransport(handler))
    response = client.post(STREAM_URL, json=_payload())

    assert response.status_code == 200
    assert calls == 1
    assert seen_authorization is None
    assert "data: [DONE]" in response.text
