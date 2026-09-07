from __future__ import annotations

import json

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.b14_runtime_config import runtime_config as rcfg


AUTO_STREAM_URL = "/api/pilot/v1/chat/completions/auto-stream-preview"
MANUAL_STREAM_URL = "/api/pilot/v1/chat/completions/stream-preview"
CHAT_URL = "/api/pilot/v1/chat/completions"
LIVE_DUMMY_KEY = "unit-live-key-auto-stream-abcdef1234567890"
KILO_MODEL = "kilo/nvidia-nemotron-3-ultra-550b-a55b-free"
KILO_UPSTREAM = "nvidia/nemotron-3-ultra-550b-a55b:free"
SECONDARY_MODEL_ID = "test/secondary-free"
SECONDARY_UPSTREAM = "test/secondary-free"
PAID_MODEL_ID = "test/paid-4k"
PAID_UPSTREAM = "test/paid-4k"


def _secondary_free_model():
    """Synthetic free route (openrouter adapter path) for fallback tests."""
    from app.pilot.catalog import CatalogModel

    return CatalogModel(
        model_id=SECONDARY_MODEL_ID,
        upstream_model=SECONDARY_UPSTREAM,
        display_name="Secondary Free (test only)",
        provider="Test Secondary Provider",
        provider_type="external",
        input_price_usd_per_1m=0.0,
        output_price_usd_per_1m=0.0,
        currency="usd",
        context_window=1_000_000,
        korean_score=3,
        latency_ms=2000,
        capabilities=frozenset({"chat", "free"}),
        region="외부",
        sort_order=30,
        credential_source="openrouter",
        platform_provider_id="",
    )


def _paid_catalog_model():
    """Synthetic paid route used to prove the free hard filter never calls it."""
    from app.pilot.catalog import CatalogModel

    return CatalogModel(
        model_id=PAID_MODEL_ID,
        upstream_model=PAID_UPSTREAM,
        display_name="Paid 4k (test only)",
        provider="Test Paid Provider",
        provider_type="external",
        input_price_usd_per_1m=3.00,
        output_price_usd_per_1m=15.00,
        currency="usd",
        context_window=200_000,
        korean_score=5,
        latency_ms=1100,
        capabilities=frozenset({"chat"}),
        region="외부",
        sort_order=5,
        credential_source="openrouter",
        platform_provider_id="",
    )


@pytest.fixture
def three_route_catalog(monkeypatch):
    """Real Kilo route + one synthetic free route + one synthetic paid route.

    Decision #1933 leaves a single real catalog route, so these tests install
    synthetic routes to keep fallback / free-filter contracts genuinely
    validated instead of silently collapsing to one candidate.
    """
    import app.pilot.catalog as cat

    original_models = cat.CATALOG_MODELS
    original_by_id = cat.CATALOG_BY_ID
    cat.CATALOG_MODELS = [*original_models, _secondary_free_model(), _paid_catalog_model()]
    cat.CATALOG_BY_ID = {m.model_id: m for m in cat.CATALOG_MODELS}
    try:
        yield
    finally:
        cat.CATALOG_MODELS = original_models
        cat.CATALOG_BY_ID = original_by_id


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
def _reset_runtime_config(monkeypatch):
    monkeypatch.delenv("KILO_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("B14_PROVIDER_MODE", raising=False)
    saved = {
        "provider_mode": rcfg.provider_mode,
        "max_response_bytes": rcfg.max_response_bytes,
    }
    rcfg.provider_mode = "mock"
    rcfg.max_response_bytes = 1024 * 1024
    yield
    rcfg.provider_mode = saved["provider_mode"]
    rcfg.max_response_bytes = saved["max_response_bytes"]


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
        app.state.stream_transport = transport
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
    assert meta["selected_model"] == KILO_MODEL
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
    explicit = {**_payload(), "model": "kilo/nvidia-nemotron-3-ultra-550b-a55b-free"}
    response = client.post(AUTO_STREAM_URL, json=explicit)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"

    manual = client.post(
        MANUAL_STREAM_URL,
        json={
            "model": "kilo/nvidia-nemotron-3-ultra-550b-a55b-free",
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


def test_free_hard_filter_never_calls_paid_catalog_candidate(three_route_catalog):
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        model = body["model"]
        calls.append(model)
        assert body["stream"] is True
        if model == KILO_UPSTREAM:
            # 5xx keeps the fallback path under test: the Kilo free-tier 429
            # (kilo_free_rate_limited) is terminal by contract and never
            # advances to another candidate.
            return httpx.Response(500, content=b"bounded")
        assert model == SECONDARY_UPSTREAM
        return httpx.Response(200, stream=_success_stream(model, "무료 fallback"))

    rcfg.provider_mode = "live"
    rcfg.api_key = LIVE_DUMMY_KEY
    response = _client(httpx.MockTransport(handler)).post(AUTO_STREAM_URL, json=_payload())

    assert response.status_code == 200
    assert calls == [KILO_UPSTREAM, SECONDARY_UPSTREAM]
    assert PAID_UPSTREAM not in calls
    frames = _json_data_frames(response.text)
    visible = next(frame for frame in frames if frame["choices"] and frame["choices"][0]["delta"].get("content"))
    meta = visible["business14"]
    assert meta["selected_model"] == SECONDARY_MODEL_ID
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

    rcfg.provider_mode = "live"
    rcfg.api_key = LIVE_DUMMY_KEY
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

    rcfg.provider_mode = "live"
    rcfg.api_key = LIVE_DUMMY_KEY
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

    rcfg.provider_mode = "live"
    rcfg.api_key = LIVE_DUMMY_KEY
    response = _client(httpx.MockTransport(handler)).post(AUTO_STREAM_URL, json=_payload())

    assert response.status_code == expected_status
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == expected_code
    assert calls == 1
    assert "secret-ish" not in response.text


@pytest.mark.parametrize(
    ("upstream_status", "expected_status", "expected_code", "expected_calls"),
    [
        # Kilo free-tier quota is terminal: it never advances to another
        # candidate. Its declared 429 status is preserved by the endpoint.
        (429, 429, "kilo_free_rate_limited", [KILO_UPSTREAM]),
        # Any other retryable transport error exhausts the resolved pool.
        (500, 502, "upstream_server_error", [KILO_UPSTREAM, SECONDARY_UPSTREAM]),
    ],
)
def test_retryable_errors_exhaust_resolved_free_candidates_before_json_failure(
    three_route_catalog,
    upstream_status: int,
    expected_status: int,
    expected_code: str,
    expected_calls: list[str],
):
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        calls.append(model)
        return httpx.Response(upstream_status, content=b"bounded")

    rcfg.provider_mode = "live"
    rcfg.api_key = LIVE_DUMMY_KEY
    response = _client(httpx.MockTransport(handler)).post(AUTO_STREAM_URL, json=_payload())

    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == expected_code
    assert calls == expected_calls


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

    rcfg.provider_mode = "live"
    rcfg.api_key = LIVE_DUMMY_KEY
    response = _client(httpx.MockTransport(handler)).post(AUTO_STREAM_URL, json=_payload())

    assert response.status_code == 200
    assert calls == [KILO_UPSTREAM]
    assert len(calls) == 1  # no fallback after a visible token was committed
    assert "부분 응답" in response.text
    assert "event: error" in response.text
    assert '"code":"stream_execution_error"' in response.text
    assert "data: [DONE]" not in response.text
    assert secret not in response.text


def test_live_keyless_route_sends_no_authorization_and_leaks_nothing(monkeypatch):
    """Keyless Kilo route: no credential crosses the boundary either way.

    The Kilo provider spec is CredentialSource.NONE, so the outbound request
    never carries an Authorization header. A stale OpenRouter key configured
    on the legacy plane must not be forwarded to it, and nothing may leak
    back to the client.
    """
    stale_key = "sk-or-v1-stale-abcdef1234567890"
    monkeypatch.setenv("KILO_API_KEY", stale_key)
    seen_auth: list[str | None] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers.get("authorization"))
        model = json.loads(request.content)["model"]
        return httpx.Response(200, stream=_success_stream(model, "안전한 응답"))

    rcfg.provider_mode = "live"
    rcfg.api_key = stale_key  # legacy OpenRouter plane must stay isolated
    response = _client(httpx.MockTransport(handler)).post(
        AUTO_STREAM_URL,
        json=_payload(business14={
            "required_capabilities": ["free"],
            "allow_external_fallback": False,
            "max_attempts": 1,
        }),
    )

    assert response.status_code == 200
    assert seen_auth == [None]
    assert stale_key not in response.text
    assert "안전한 응답" in response.text
    assert response.text.count("data: [DONE]") == 1


def test_live_missing_key_is_anonymous_with_no_authorization_header():
    """Keyless Kilo route: no key is required, and none is ever sent.

    Decision #1933 removed the secret-backed routes, so a missing key is not
    an error here. The security contract becomes "zero key material": exactly
    one anonymous upstream call, no Authorization header, nothing leaked.
    The secret-required fail-closed path is covered by
    test_platform_provider_credential_plane.py (Agnes).
    """
    calls = 0
    seen_auth: list[str | None] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        seen_auth.append(request.headers.get("authorization"))
        model = json.loads(request.content)["model"]
        return httpx.Response(200, stream=_success_stream(model, "익명 응답"))

    rcfg.provider_mode = "live"
    rcfg.api_key = ""
    response = _client(httpx.MockTransport(handler)).post(AUTO_STREAM_URL, json=_payload())

    assert response.status_code == 200
    assert calls == 1
    assert seen_auth == [None]
    assert "익명 응답" in response.text
    assert "data: [DONE]" in response.text
