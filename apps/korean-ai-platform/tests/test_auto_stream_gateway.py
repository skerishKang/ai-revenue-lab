from __future__ import annotations

import json

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.openrouter_config import openrouter_config as orcfg


AUTO_STREAM_URL = "/api/pilot/v1/chat/completions/auto-stream-preview"
MANUAL_STREAM_URL = "/api/pilot/v1/chat/completions/stream-preview"
CHAT_URL = "/api/pilot/v1/chat/completions"
LIVE_DUMMY_KEY = "unit-live-key-auto-stream-abcdef1234567890"


class _ChunkStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes], *, error_after: Exception | None = None):
        self.chunks = list(chunks)
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


def _payload(**overrides):
    payload = {
        "model": "b14/auto",
        "messages": [{"role": "user", "content": "안녕하세요"}],
        "stream": True,
        "business14": {
            "task_type": "general",
            "required_capabilities": ["free"],
            "optimize_for": "balanced",
            "allow_external_fallback": True,
            "max_attempts": 2,
        },
    }
    payload.update(overrides)
    return payload


def _client(transport: httpx.AsyncBaseTransport | None = None) -> TestClient:
    app = create_app()
    if transport is not None:
        app.state.openrouter_stream_transport = transport
    return TestClient(app)


def _data(payload: dict) -> bytes:
    return f"data: {json.dumps(payload)}\n\n".encode()


def _content_frame(model: str, content: str) -> bytes:
    return _data(
        {
            "id": "upstream_auto_1",
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": content},
                    "finish_reason": None,
                }
            ],
        }
    )


def _usage_frame(model: str) -> bytes:
    return _data(
        {
            "id": "upstream_auto_1",
            "model": model,
            "choices": [],
            "usage": {
                "prompt_tokens": 3,
                "completion_tokens": 2,
                "total_tokens": 5,
            },
        }
    )


def _finish_frame(model: str) -> bytes:
    return _data(
        {
            "id": "upstream_auto_1",
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop",
                }
            ],
        }
    )


def _success_stream(model: str, content: str = "자동 경로 응답") -> _ChunkStream:
    return _ChunkStream(
        [
            _content_frame(model, content),
            _finish_frame(model),
            b"data: [DONE]\n\n",
        ]
    )


def _json_data_frames(text: str) -> list[dict]:
    out: list[dict] = []
    for line in text.splitlines():
        if not line.startswith("data: "):
            continue
        value = line[6:]
        if value == "[DONE]":
            continue
        out.append(json.loads(value))
    return out


def test_mock_auto_preview_accepts_b14_auto_and_preserves_router_metadata():
    response = _client().post(AUTO_STREAM_URL, json=_payload())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache, no-store"
    assert response.text.count("data: [DONE]") == 1

    frames = _json_data_frames(response.text)
    first = next(frame for frame in frames if frame["choices"] and frame["choices"][0]["delta"].get("content"))
    meta = first["business14"]
    assert meta["route_mode"] == "auto"
    assert meta["selected_model"] == "stealth/ox-alpha"
    assert meta["fallback_used"] is False
    assert meta["attempt_count"] == 1
    assert meta["committed"] is True
    assert meta["provider_mode"] == "mock"
    assert "capabilities:free" in meta["reason_codes"]
    assert meta["route_evidence_status"] == "mock_no_upstream_call"


def test_auto_preview_requires_stream_true():
    payload = _payload()
    payload.pop("stream")
    response = _client().post(AUTO_STREAM_URL, json=payload)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_auto_preview_rejects_explicit_model_while_manual_preview_still_owns_it():
    client = _client()
    explicit = {**_payload(), "model": "openrouter/free"}
    response = client.post(AUTO_STREAM_URL, json=explicit)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"

    manual = client.post(
        MANUAL_STREAM_URL,
        json={
            "model": "openrouter/free",
            "messages": [{"role": "user", "content": "안녕하세요"}],
            "stream": True,
        },
    )
    assert manual.status_code == 200
    assert "data: [DONE]" in manual.text
    manual_frames = _json_data_frames(manual.text)
    assert manual_frames[0]["business14"]["route_mode"] == "manual"


def test_canonical_endpoint_still_rejects_stream_true_for_b14_auto():
    response = _client().post(CHAT_URL, json=_payload())
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "stream_not_supported"


def test_free_hard_filter_never_calls_paid_catalog_candidate():
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        model = body["model"]
        calls.append(model)
        assert body["stream"] is True
        if model == "stealth/ox-alpha":
            return httpx.Response(429, content=b"bounded")
        assert model == "openrouter/free"
        return httpx.Response(200, stream=_success_stream(model, "무료 fallback"))

    orcfg.provider_mode = "live"
    orcfg.api_key = LIVE_DUMMY_KEY
    response = _client(httpx.MockTransport(handler)).post(AUTO_STREAM_URL, json=_payload())

    assert response.status_code == 200
    assert calls == ["stealth/ox-alpha", "openrouter/free"]
    assert "google/gemini-2.5-flash" not in calls
    frames = _json_data_frames(response.text)
    visible = next(frame for frame in frames if frame["choices"] and frame["choices"][0]["delta"].get("content"))
    meta = visible["business14"]
    assert meta["selected_model"] == "openrouter/free"
    assert meta["fallback_used"] is True
    assert meta["attempt_count"] == 2
    assert meta["committed"] is True
    assert "capabilities:free" in meta["reason_codes"]


def test_metadata_only_before_content_does_not_make_empty_stream_successful():
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        model = body["model"]
        return httpx.Response(
            200,
            stream=_ChunkStream([_usage_frame(model), b"data: [DONE]\n\n"]),
        )

    orcfg.provider_mode = "live"
    orcfg.api_key = LIVE_DUMMY_KEY
    response = _client(httpx.MockTransport(handler)).post(
        AUTO_STREAM_URL,
        json=_payload(business14={
            "required_capabilities": ["free"],
            "allow_external_fallback": False,
            "max_attempts": 1,
        }),
    )

    assert response.status_code == 502
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == "empty_stream_answer"
    assert "data: " not in response.text


def test_usage_metadata_is_buffered_then_emitted_before_first_visible_content():
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        model = body["model"]
        return httpx.Response(
            200,
            stream=_ChunkStream(
                [
                    _usage_frame(model),
                    _content_frame(model, "첫 토큰"),
                    _finish_frame(model),
                    b"data: [DONE]\n\n",
                ]
            ),
        )

    orcfg.provider_mode = "live"
    orcfg.api_key = LIVE_DUMMY_KEY
    response = _client(httpx.MockTransport(handler)).post(
        AUTO_STREAM_URL,
        json=_payload(business14={
            "required_capabilities": ["free"],
            "allow_external_fallback": False,
            "max_attempts": 1,
        }),
    )

    assert response.status_code == 200
    frames = _json_data_frames(response.text)
    assert frames[0]["choices"] == []
    assert frames[0]["usage"] == {
        "prompt_tokens": 3,
        "completion_tokens": 2,
        "total_tokens": 5,
    }
    assert frames[0]["business14"]["committed"] is False
    assert frames[1]["choices"][0]["delta"]["content"] == "첫 토큰"
    assert frames[1]["business14"]["committed"] is True


@pytest.mark.parametrize(
    ("upstream_status", "expected_status", "expected_code"),
    [
        (401, 401, "upstream_auth_failed"),
        (403, 401, "upstream_auth_failed"),
        (422, 502, "upstream_client_error"),
    ],
)
def test_nonretryable_pre_token_errors_stay_json_before_sse_start(
    upstream_status: int,
    expected_status: int,
    expected_code: str,
):
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(upstream_status, content=b"secret-ish upstream body")

    orcfg.provider_mode = "live"
    orcfg.api_key = LIVE_DUMMY_KEY
    response = _client(httpx.MockTransport(handler)).post(AUTO_STREAM_URL, json=_payload())

    assert response.status_code == expected_status
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == expected_code
    assert calls == 1
    assert "secret-ish" not in response.text


@pytest.mark.parametrize(
    ("upstream_status", "expected_status", "expected_code"),
    [
        (429, 429, "upstream_rate_limited"),
        (500, 502, "upstream_server_error"),
    ],
)
def test_retryable_errors_exhaust_resolved_free_candidates_before_json_failure(
    upstream_status: int,
    expected_status: int,
    expected_code: str,
):
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        calls.append(model)
        return httpx.Response(upstream_status, content=b"bounded")

    orcfg.provider_mode = "live"
    orcfg.api_key = LIVE_DUMMY_KEY
    response = _client(httpx.MockTransport(handler)).post(AUTO_STREAM_URL, json=_payload())

    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == expected_code
    assert calls == ["stealth/ox-alpha", "openrouter/free"]


def test_post_visible_token_failure_emits_bounded_error_without_fallback_or_done():
    calls: list[str] = []
    secret = "DO-NOT-EXPOSE-AUTO-STREAM-SECRET"

    async def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        calls.append(model)
        return httpx.Response(
            200,
            stream=_ChunkStream(
                [_content_frame(model, "부분 응답")],
                error_after=RuntimeError(secret),
            ),
        )

    orcfg.provider_mode = "live"
    orcfg.api_key = LIVE_DUMMY_KEY
    response = _client(httpx.MockTransport(handler)).post(AUTO_STREAM_URL, json=_payload())

    assert response.status_code == 200
    assert calls == ["stealth/ox-alpha"]
    assert "부분 응답" in response.text
    assert "event: error" in response.text
    assert '"code":"stream_execution_error"' in response.text
    assert "data: [DONE]" not in response.text
    assert secret not in response.text


def test_live_success_keeps_authorization_upstream_only_and_done_once():
    secret = "unit-auto-stream-secret-abcdef1234567890"
    seen_auth: list[str | None] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers.get("authorization"))
        model = json.loads(request.content)["model"]
        return httpx.Response(200, stream=_success_stream(model, "안전한 응답"))

    orcfg.provider_mode = "live"
    orcfg.api_key = secret
    response = _client(httpx.MockTransport(handler)).post(
        AUTO_STREAM_URL,
        json=_payload(business14={
            "required_capabilities": ["free"],
            "allow_external_fallback": False,
            "max_attempts": 1,
        }),
    )

    assert response.status_code == 200
    assert seen_auth == [f"Bearer {secret}"]
    assert secret not in response.text
    assert "안전한 응답" in response.text
    assert response.text.count("data: [DONE]") == 1


def test_live_missing_key_is_json_503_without_transport_call():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b"data: [DONE]\n\n")

    orcfg.provider_mode = "live"
    orcfg.api_key = ""
    response = _client(httpx.MockTransport(handler)).post(AUTO_STREAM_URL, json=_payload())

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "pilot_not_configured"
    assert calls == 0
