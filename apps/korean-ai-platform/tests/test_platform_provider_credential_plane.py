"""Network-free tests for the generic platform-owned credential plane (#917).

OpenRouter is retired (#1933 S2-b) and the Agnes route is removed from
production. These tests exercise the same credential contracts through a
synthetic platform_secret provider so the plane stays genuinely validated
rather than silently passing. No real secret is read, printed, committed,
or sent. Every test uses a synthetic non-secret key in the environment only.
"""

from __future__ import annotations

import json

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot import platform as plat
from app.pilot import platform_secrets as ps
from app.pilot.catalog import get_catalog_by_id
from app.pilot.errors import NoSafeRoute, PilotNotConfigured, UpstreamAuthFailed
from app.pilot.router_core import resolve_auto_route, resolve_manual_route

TEST_PROVIDER_ID = "test-credential-plane"
TEST_BINDING = "TEST_CREDENTIAL_PLANE_API_KEY"
TEST_ORIGIN = "https://api.test-credential-plane.invalid/v1"
TEST_HOST = "api.test-credential-plane.invalid"
TEST_MODEL_ID = "test-credential-plane/test-model"
TEST_UPSTREAM = "test-model"
TEST_PROVIDER = "Test Credential Plane"


def _ensure_test_provider() -> None:
    if ps.get_platform_provider(TEST_PROVIDER_ID) is None:
        ps.register_platform_provider(
            ps.PlatformProviderSpec(
                provider_id=TEST_PROVIDER_ID,
                credential_source=ps.CredentialSource.PLATFORM_SECRET,
                credential_binding_name=TEST_BINDING,
                base_origin=TEST_ORIGIN,
                allowed_hosts=(TEST_HOST,),
                enabled=True,
            )
        )


_ensure_test_provider()


def _test_catalog_model():
    from app.pilot.catalog import CatalogModel

    return CatalogModel(
        model_id=TEST_MODEL_ID,
        upstream_model=TEST_UPSTREAM,
        display_name="Test Credential Plane Model",
        provider=TEST_PROVIDER,
        provider_type="platform",
        input_price_usd_per_1m=None,
        output_price_usd_per_1m=None,
        currency="usd",
        context_window=200000,
        korean_score=4,
        latency_ms=900,
        capabilities=frozenset({"chat"}),
        region="외부",
        sort_order=70,
        credential_source="platform_secret",
        platform_provider_id=TEST_PROVIDER_ID,
    )


@pytest.fixture(autouse=True)
def _test_catalog_route(monkeypatch):
    import app.pilot.catalog as cat

    _ensure_test_provider()
    original_models = cat.CATALOG_MODELS
    original_by_id = cat.CATALOG_BY_ID
    extra = _test_catalog_model()
    cat.CATALOG_MODELS = [*original_models, extra]
    cat.CATALOG_BY_ID = {m.model_id: m for m in cat.CATALOG_MODELS}
    try:
        yield extra
    finally:
        cat.CATALOG_MODELS = original_models
        cat.CATALOG_BY_ID = original_by_id


_SYNTH_KEY = "tstp_live_abcdefghijklmnopqrstuvwxyz1234"
_SYNTH_ALT_KEY = "alt_live_zyxwvutsrqponmlkjihgfedcba5678"


class _Chunk(httpx.AsyncByteStream):
    def __init__(self, data: bytes):
        self._d = data
        self.closed = False

    async def __aiter__(self):
        for piece in [self._d[i:i + 16] for i in range(0, len(self._d), 16)]:
            yield piece

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _test_env(monkeypatch):
    """Default: synthetic secret absent (fail-closed baseline)."""
    monkeypatch.delenv(TEST_BINDING, raising=False)
    monkeypatch.delenv("B14_PROVIDER_MODE", raising=False)
    assert ps.get_platform_provider(TEST_PROVIDER_ID) is not None
    yield
    monkeypatch.delenv(TEST_BINDING, raising=False)


def _auto_pool(decision) -> set[str]:
    pool = {decision.selected_model}
    for fb in decision.eligible_fallback:
        pool.add(fb["model_id"])
    return pool


def test_agnes_route_retired_from_production():
    # Agnes provider and catalog entry are removed (#1933 S2-b).
    assert ps.get_platform_provider("agnes-ai") is None
    assert get_catalog_by_id("agnes-ai/agnes-2.5-flash") is None


# ---------------------------------------------------------------------------
# Catalog / registration
# ---------------------------------------------------------------------------
def test_platform_provider_registered_with_nonsecret_metadata():
    model = get_catalog_by_id(TEST_MODEL_ID)
    assert model is not None
    assert model.upstream_model == TEST_UPSTREAM
    assert model.provider == TEST_PROVIDER
    assert model.credential_source == "platform_secret"
    assert model.platform_provider_id == TEST_PROVIDER_ID

    spec = ps.get_platform_provider(TEST_PROVIDER_ID)
    assert spec is not None
    assert spec.credential_source == ps.CredentialSource.PLATFORM_SECRET
    assert spec.credential_binding_name == TEST_BINDING
    assert spec.base_origin == TEST_ORIGIN
    assert spec.allowed_hosts == (TEST_HOST,)


def test_platform_model_has_no_free_capability():
    model = get_catalog_by_id(TEST_MODEL_ID)
    assert "free" not in model.capabilities


# ---------------------------------------------------------------------------
# Manual route: secret present / missing
# ---------------------------------------------------------------------------
def test_manual_route_eligible_when_secret_present(monkeypatch):
    monkeypatch.setenv(TEST_BINDING, _SYNTH_KEY)
    decision = resolve_manual_route(TEST_MODEL_ID)
    assert decision.selected_model == TEST_MODEL_ID
    assert decision.selected_upstream_model == TEST_UPSTREAM
    assert decision.credential_source == "platform_secret"
    assert decision.platform_provider_id == TEST_PROVIDER_ID
    assert decision.credential_available is True
    assert decision.credential_status == "key_available"


def test_manual_route_fails_closed_when_secret_missing():
    with pytest.raises(NoSafeRoute) as info:
        resolve_manual_route(TEST_MODEL_ID)
    assert info.value.reason_code == "provider_secret_missing"
    assert info.value.upstream_called is False


# ---------------------------------------------------------------------------
# b14/auto eligibility tied to credential
# ---------------------------------------------------------------------------
def test_b14_auto_excludes_platform_model_when_secret_missing():
    decision = resolve_auto_route(
        task_type="general",
        required_capabilities=["chat"],
        optimize_for="balanced",
        allow_external_fallback=True,
    )
    assert TEST_MODEL_ID not in _auto_pool(decision)
    reasons = {c.get("model_id"): c.get("reason") for c in decision.excluded_candidates}
    assert reasons.get(TEST_MODEL_ID) == "provider_secret_missing"


def test_b14_auto_can_include_platform_model_when_secret_present(monkeypatch):
    monkeypatch.setenv(TEST_BINDING, _SYNTH_KEY)
    decision = resolve_auto_route(
        task_type="general",
        required_capabilities=["chat"],
        optimize_for="balanced",
        allow_external_fallback=True,
    )
    assert TEST_MODEL_ID in _auto_pool(decision)
    reasons = {c.get("model_id"): c.get("reason") for c in decision.excluded_candidates}
    assert reasons.get(TEST_MODEL_ID) != "provider_secret_missing"


# ---------------------------------------------------------------------------
# Completed-JSON call: secret resolution, isolation, fail-closed
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_platform_call_uses_only_its_own_secret_and_fixed_origin(monkeypatch):
    monkeypatch.setenv(TEST_BINDING, _SYNTH_KEY)
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "r1",
                "model": TEST_UPSTREAM,
                "choices": [
                    {"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    response = await plat.call_platform_chat_completions(
        model_id=TEST_MODEL_ID,
        upstream_model=TEST_UPSTREAM,
        provider=TEST_PROVIDER,
        platform_provider_id=TEST_PROVIDER_ID,
        messages=[{"role": "user", "content": "hi"}],
        transport=httpx.MockTransport(handler),
    )
    assert captured["url"] == f"{TEST_ORIGIN}/chat/completions"
    assert captured["auth"] == f"Bearer {_SYNTH_KEY}"
    assert captured["body"]["model"] == TEST_UPSTREAM
    assert response["choices"][0]["message"]["content"] == "ok"


@pytest.mark.asyncio
async def test_platform_call_fails_closed_without_upstream_when_secret_missing(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        raise AssertionError("missing secret must fail before network")

    with pytest.raises(PilotNotConfigured):
        await plat.call_platform_chat_completions(
            model_id=TEST_MODEL_ID,
            upstream_model=TEST_UPSTREAM,
            provider=TEST_PROVIDER,
            platform_provider_id=TEST_PROVIDER_ID,
            messages=[{"role": "user", "content": "hi"}],
            transport=httpx.MockTransport(handler),
        )
    assert calls["n"] == 0


@pytest.mark.asyncio
async def test_platform_call_mock_mode_is_zero_network(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "mock")

    def handler(request):
        raise AssertionError("mock mode must not call upstream")

    response = await plat.call_platform_chat_completions(
        model_id=TEST_MODEL_ID,
        upstream_model=TEST_UPSTREAM,
        provider=TEST_PROVIDER,
        platform_provider_id=TEST_PROVIDER_ID,
        messages=[{"role": "user", "content": "hi"}],
        transport=httpx.MockTransport(handler),
    )
    assert response["_mock"] is True


# ---------------------------------------------------------------------------
# Cross-provider key isolation (no reuse of one Provider's credential)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_secret_is_not_reused_across_providers(monkeypatch):
    monkeypatch.setenv(TEST_BINDING, _SYNTH_KEY)
    monkeypatch.setenv("TEST_ALT_API_KEY", _SYNTH_ALT_KEY)
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")

    ps.register_platform_provider(
        ps.PlatformProviderSpec(
            provider_id="test-alt",
            credential_source=ps.CredentialSource.PLATFORM_SECRET,
            credential_binding_name="TEST_ALT_API_KEY",
            base_origin="https://api.testalt.invalid/v1",
            allowed_hosts=("api.testalt.invalid",),
        )
    )

    captured = {}

    def handler(request):
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(
            200,
            json={
                "id": "r2",
                "model": TEST_UPSTREAM,
                "choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            },
        )

    await plat.call_platform_chat_completions(
        model_id=TEST_MODEL_ID,
        upstream_model=TEST_UPSTREAM,
        provider=TEST_PROVIDER,
        platform_provider_id=TEST_PROVIDER_ID,
        messages=[{"role": "user", "content": "hi"}],
        transport=httpx.MockTransport(handler),
    )
    assert captured["auth"] == f"Bearer {_SYNTH_KEY}"
    assert _SYNTH_ALT_KEY not in captured["auth"]


# ---------------------------------------------------------------------------
# Request BYOK cannot overwrite a platform-owned credential
# ---------------------------------------------------------------------------
def test_platform_call_rejects_external_key_by_construction(monkeypatch):
    import inspect

    params = inspect.signature(plat.call_platform_chat_completions).parameters
    assert "byok_key" not in params
    assert "api_key" not in params
    assert "provider_key" not in params


def test_alpha_gateway_ignores_byok_header_for_platform_model(monkeypatch):
    monkeypatch.setenv(TEST_BINDING, _SYNTH_KEY)
    monkeypatch.setenv("B14_PROVIDER_MODE", "mock")
    client = TestClient(create_app())
    response = client.post(
        "/api/pilot/v1/chat/completions",
        json={
            "model": TEST_MODEL_ID,
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers={"X-Business14-Provider-Key": "sk-attacker-byok-1234567890"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["business14"]["provider"] == TEST_PROVIDER
    assert "sk-attacker-byok-1234567890" not in json.dumps(data)


# ---------------------------------------------------------------------------
# Arbitrary upstream host injection rejected
# ---------------------------------------------------------------------------
def test_platform_origin_validation_rejects_bad_host():
    with pytest.raises(ValueError):
        ps.PlatformProviderSpec(
            provider_id="bad",
            credential_source=ps.CredentialSource.PLATFORM_SECRET,
            credential_binding_name="BAD_KEY",
            base_origin="https://evil.example.com/v1",
            allowed_hosts=(TEST_HOST,),
        )


def test_platform_origin_validation_rejects_localhost_and_http():
    for origin in ("http://api.test-credential-plane.invalid/v1", "https://localhost/v1", "https://10.0.0.1/v1"):
        with pytest.raises(ValueError):
            ps.PlatformProviderSpec(
                provider_id="bad",
                credential_source=ps.CredentialSource.PLATFORM_SECRET,
                credential_binding_name="BAD_KEY",
                base_origin=origin,
                allowed_hosts=(TEST_HOST,),
            )


# ---------------------------------------------------------------------------
# Secret redaction: never in logs / responses / errors / stream events
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_secret_absent_from_errors_and_response(monkeypatch, caplog):
    import logging

    monkeypatch.setenv(TEST_BINDING, _SYNTH_KEY)
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    caplog.set_level(logging.ERROR, logger="korean-ai-platform.pilot")

    captured = {}

    def handler(request):
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(401, content=b"unauthorized")

    with pytest.raises(UpstreamAuthFailed):
        await plat.call_platform_chat_completions(
            model_id=TEST_MODEL_ID,
            upstream_model=TEST_UPSTREAM,
            provider=TEST_PROVIDER,
            platform_provider_id=TEST_PROVIDER_ID,
            messages=[{"role": "user", "content": "hi"}],
            transport=httpx.MockTransport(handler),
        )
    log_text = json.dumps([rec.message for rec in caplog.records])
    assert _SYNTH_KEY not in log_text
    assert TEST_BINDING not in log_text


@pytest.mark.asyncio
async def test_secret_absent_from_stream_events(monkeypatch):
    monkeypatch.setenv(TEST_BINDING, _SYNTH_KEY)
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")

    payload = (
        b'data: {"id":"s1","model":"test-model","choices":[{"delta":{"content":"a"},"finish_reason":null}]}\n\n'
        b'data: {"id":"s1","model":"test-model","choices":[{"delta":{"content":"b"},"finish_reason":"stop"}]}\n\n'
        b"data: [DONE]\n\n"
    )

    def handler(request):
        return httpx.Response(200, stream=_Chunk(payload))

    events = [
        e
        async for e in plat.stream_platform_chat_completions(
            model_id=TEST_MODEL_ID,
            upstream_model=TEST_UPSTREAM,
            provider=TEST_PROVIDER,
            platform_provider_id=TEST_PROVIDER_ID,
            messages=[{"role": "user", "content": "hi"}],
            transport=httpx.MockTransport(handler),
        )
    ]
    assert events[-1].done is True
    assert all(_SYNTH_KEY not in repr(e) for e in events)
    assert all(TEST_BINDING not in repr(e) for e in events)


# ---------------------------------------------------------------------------
# Streaming compatibility: request translation + missing-secret fail-closed
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_platform_stream_translates_request_and_uses_secret(monkeypatch):
    monkeypatch.setenv(TEST_BINDING, _SYNTH_KEY)
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    captured = {}

    payload = (
        b'data: {"id":"s1","model":"test-model","choices":[{"delta":{"content":"a"},"finish_reason":null}]}\n\n'
        b"data: [DONE]\n\n"
    )

    def handler(request):
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, stream=_Chunk(payload))

    events = [
        e
        async for e in plat.stream_platform_chat_completions(
            model_id=TEST_MODEL_ID,
            upstream_model=TEST_UPSTREAM,
            provider=TEST_PROVIDER,
            platform_provider_id=TEST_PROVIDER_ID,
            messages=[{"role": "user", "content": "hi"}],
            transport=httpx.MockTransport(handler),
        )
    ]
    assert captured["url"] == f"{TEST_ORIGIN}/chat/completions"
    assert captured["auth"] == f"Bearer {_SYNTH_KEY}"
    assert captured["body"]["model"] == TEST_UPSTREAM
    assert captured["body"]["stream"] is True
    assert events[0].delta_content == "a"
    assert events[-1].done is True


@pytest.mark.asyncio
async def test_platform_stream_fails_closed_without_upstream_when_secret_missing(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        raise AssertionError("missing secret must fail before network")

    with pytest.raises(PilotNotConfigured):
        [
            e
            async for e in plat.stream_platform_chat_completions(
                model_id=TEST_MODEL_ID,
                upstream_model=TEST_UPSTREAM,
                provider=TEST_PROVIDER,
                platform_provider_id=TEST_PROVIDER_ID,
                messages=[{"role": "user", "content": "hi"}],
                transport=httpx.MockTransport(handler),
            )
        ]
    assert calls["n"] == 0


# ---------------------------------------------------------------------------
# Gateway-level: explicit selection (mock), missing fails closed (live)
# ---------------------------------------------------------------------------
def test_gateway_explicit_platform_selection_mock_mode(monkeypatch):
    monkeypatch.setenv(TEST_BINDING, _SYNTH_KEY)
    monkeypatch.setenv("B14_PROVIDER_MODE", "mock")
    client = TestClient(create_app())
    response = client.post(
        "/api/pilot/v1/chat/completions",
        json={
            "model": TEST_MODEL_ID,
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["model"] == TEST_UPSTREAM
    assert data["business14"]["provider"] == TEST_PROVIDER
    assert data["business14"]["model_route"] == TEST_MODEL_ID
    assert TEST_BINDING not in json.dumps(data)


def test_gateway_platform_fails_closed_when_secret_missing_live(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.delenv(TEST_BINDING, raising=False)
    client = TestClient(create_app())
    response = client.post(
        "/api/pilot/v1/chat/completions",
        json={
            "model": TEST_MODEL_ID,
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "no_safe_route"
    assert TEST_BINDING not in json.dumps(response.json())


# ---------------------------------------------------------------------------
# Gateway-level: platform_secret STREAMING closure
# ---------------------------------------------------------------------------
_STREAM_URL = "/api/pilot/v1/chat/completions/stream-preview"


def test_stream_preview_platform_secret_streams_when_secret_present(monkeypatch):
    """platform_secret route streams via stream-preview (mock mode)."""
    monkeypatch.setenv(TEST_BINDING, _SYNTH_KEY)
    monkeypatch.setenv("B14_PROVIDER_MODE", "mock")
    client = TestClient(create_app())
    response = client.post(
        _STREAM_URL,
        json={
            "model": TEST_MODEL_ID,
            "stream": True,
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    text = response.text
    assert "Mock" in text or "delta" in text or "이것은" in text
    assert _SYNTH_KEY not in text
    assert TEST_BINDING not in text


def test_stream_preview_platform_secret_fails_closed_when_secret_missing(monkeypatch):
    """platform_secret streaming fails closed (zero upstream) without secret."""
    monkeypatch.setenv("B14_PROVIDER_MODE", "mock")
    monkeypatch.delenv(TEST_BINDING, raising=False)
    client = TestClient(create_app())
    response = client.post(
        _STREAM_URL,
        json={
            "model": TEST_MODEL_ID,
            "stream": True,
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert response.status_code == 503
    body = response.json()
    assert TEST_BINDING not in json.dumps(body)


def test_stream_preview_kilo_route_still_streams(monkeypatch):
    """Keyless Kilo manual route streams via stream-preview (mock mode)."""
    monkeypatch.delenv(TEST_BINDING, raising=False)
    client = TestClient(create_app())
    response = client.post(
        _STREAM_URL,
        json={
            "model": "kilo/nvidia-nemotron-3-ultra-550b-a55b-free",
            "stream": True,
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert TEST_BINDING not in response.text
    assert _SYNTH_KEY not in response.text
