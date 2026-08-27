"""Network-free tests for the generic platform-owned credential plane (#917)
and the Agnes AI onboarding (#921).

No real secret is read, printed, committed, or sent. Every test uses a
synthetic non-secret key in the environment only.
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

_SYNTH_AGNES_KEY = "ags_live_abcdefghijklmnopqrstuvwxyz1234"
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
def _agnes_env(monkeypatch):
    """Default: Agnes secret absent (fail-closed baseline)."""
    monkeypatch.delenv("AGNES_API_KEY", raising=False)
    monkeypatch.delenv("B14_PROVIDER_MODE", raising=False)
    assert ps.get_platform_provider("agnes-ai") is not None
    yield
    monkeypatch.delenv("AGNES_API_KEY", raising=False)


def _auto_pool(decision) -> set[str]:
    pool = {decision.selected_model}
    for fb in decision.eligible_fallback:
        pool.add(fb["model_id"])
    return pool


# ---------------------------------------------------------------------------
# Catalog / registration
# ---------------------------------------------------------------------------
def test_agnes_is_registered_in_catalog_with_nonsecret_metadata():
    model = get_catalog_by_id("agnes-ai/agnes-2.5-flash")
    assert model is not None
    assert model.upstream_model == "agnes-2.5-flash"
    assert model.provider == "Agnes AI"
    assert model.credential_source == "platform_secret"
    assert model.platform_provider_id == "agnes-ai"

    spec = ps.get_platform_provider("agnes-ai")
    assert spec is not None
    assert spec.credential_source == ps.CredentialSource.PLATFORM_SECRET
    assert spec.credential_binding_name == "AGNES_API_KEY"
    assert spec.base_origin == "https://apihub.agnes-ai.com/v1"
    assert spec.allowed_hosts == ("apihub.agnes-ai.com",)


def test_agnes_has_no_free_capability_and_is_not_in_public_free_pool():
    model = get_catalog_by_id("agnes-ai/agnes-2.5-flash")
    assert "free" not in model.capabilities


# ---------------------------------------------------------------------------
# Manual route: secret present / missing
# ---------------------------------------------------------------------------
def test_agnes_manual_route_eligible_when_secret_present(monkeypatch):
    monkeypatch.setenv("AGNES_API_KEY", _SYNTH_AGNES_KEY)
    decision = resolve_manual_route("agnes-ai/agnes-2.5-flash")
    assert decision.selected_model == "agnes-ai/agnes-2.5-flash"
    assert decision.selected_upstream_model == "agnes-2.5-flash"
    assert decision.credential_source == "platform_secret"
    assert decision.platform_provider_id == "agnes-ai"
    assert decision.credential_available is True
    assert decision.credential_status == "key_available"


def test_agnes_manual_route_fails_closed_when_secret_missing():
    with pytest.raises(NoSafeRoute) as info:
        resolve_manual_route("agnes-ai/agnes-2.5-flash")
    assert info.value.reason_code == "provider_secret_missing"
    assert info.value.upstream_called is False


# ---------------------------------------------------------------------------
# b14/auto eligibility tied to credential
# ---------------------------------------------------------------------------
def test_b14_auto_excludes_agnes_when_secret_missing():
    decision = resolve_auto_route(
        task_type="general",
        required_capabilities=["chat"],
        optimize_for="balanced",
        allow_external_fallback=True,
    )
    assert "agnes-ai/agnes-2.5-flash" not in _auto_pool(decision)
    reasons = {c.get("model_id"): c.get("reason") for c in decision.excluded_candidates}
    assert reasons.get("agnes-ai/agnes-2.5-flash") == "provider_secret_missing"


def test_b14_auto_can_include_agnes_when_secret_present(monkeypatch):
    monkeypatch.setenv("AGNES_API_KEY", _SYNTH_AGNES_KEY)
    decision = resolve_auto_route(
        task_type="general",
        required_capabilities=["chat"],
        optimize_for="balanced",
        allow_external_fallback=True,
    )
    assert "agnes-ai/agnes-2.5-flash" in _auto_pool(decision)
    reasons = {c.get("model_id"): c.get("reason") for c in decision.excluded_candidates}
    assert reasons.get("agnes-ai/agnes-2.5-flash") != "provider_secret_missing"


# ---------------------------------------------------------------------------
# Completed-JSON call: secret resolution, isolation, fail-closed
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_platform_call_uses_only_its_own_secret_and_fixed_origin(monkeypatch):
    monkeypatch.setenv("AGNES_API_KEY", _SYNTH_AGNES_KEY)
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
                "model": "agnes-2.5-flash",
                "choices": [
                    {"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    response = await plat.call_platform_chat_completions(
        model_id="agnes-ai/agnes-2.5-flash",
        upstream_model="agnes-2.5-flash",
        provider="Agnes AI",
        platform_provider_id="agnes-ai",
        messages=[{"role": "user", "content": "hi"}],
        transport=httpx.MockTransport(handler),
    )
    assert captured["url"] == "https://apihub.agnes-ai.com/v1/chat/completions"
    assert captured["auth"] == f"Bearer {_SYNTH_AGNES_KEY}"
    assert captured["body"]["model"] == "agnes-2.5-flash"
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
            model_id="agnes-ai/agnes-2.5-flash",
            upstream_model="agnes-2.5-flash",
            provider="Agnes AI",
            platform_provider_id="agnes-ai",
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
        model_id="agnes-ai/agnes-2.5-flash",
        upstream_model="agnes-2.5-flash",
        provider="Agnes AI",
        platform_provider_id="agnes-ai",
        messages=[{"role": "user", "content": "hi"}],
        transport=httpx.MockTransport(handler),
    )
    assert response["_mock"] is True


# ---------------------------------------------------------------------------
# Cross-provider key isolation (no reuse of one Provider's credential)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_secret_is_not_reused_across_providers(monkeypatch):
    monkeypatch.setenv("AGNES_API_KEY", _SYNTH_AGNES_KEY)
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
                "model": "agnes-2.5-flash",
                "choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            },
        )

    await plat.call_platform_chat_completions(
        model_id="agnes-ai/agnes-2.5-flash",
        upstream_model="agnes-2.5-flash",
        provider="Agnes AI",
        platform_provider_id="agnes-ai",
        messages=[{"role": "user", "content": "hi"}],
        transport=httpx.MockTransport(handler),
    )
    assert captured["auth"] == f"Bearer {_SYNTH_AGNES_KEY}"
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


def test_alpha_gateway_ignores_byok_header_for_agnes(monkeypatch):
    monkeypatch.setenv("AGNES_API_KEY", _SYNTH_AGNES_KEY)
    monkeypatch.setenv("B14_PROVIDER_MODE", "mock")
    client = TestClient(create_app())
    response = client.post(
        "/api/pilot/v1/chat/completions",
        json={
            "model": "agnes-ai/agnes-2.5-flash",
            "messages": [{"role": "user", "content": "hi"}],
        },
        headers={"X-Business14-Provider-Key": "sk-attacker-byok-1234567890"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["business14"]["provider"] == "Agnes AI"
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
            allowed_hosts=("apihub.agnes-ai.com",),
        )


def test_platform_origin_validation_rejects_localhost_and_http():
    for origin in ("http://apihub.agnes-ai.com/v1", "https://localhost/v1", "https://10.0.0.1/v1"):
        with pytest.raises(ValueError):
            ps.PlatformProviderSpec(
                provider_id="bad",
                credential_source=ps.CredentialSource.PLATFORM_SECRET,
                credential_binding_name="BAD_KEY",
                base_origin=origin,
                allowed_hosts=("apihub.agnes-ai.com",),
            )


# ---------------------------------------------------------------------------
# Secret redaction: never in logs / responses / errors / stream events
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_secret_absent_from_errors_and_response(monkeypatch, caplog):
    import logging

    monkeypatch.setenv("AGNES_API_KEY", _SYNTH_AGNES_KEY)
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    caplog.set_level(logging.ERROR, logger="korean-ai-platform.pilot")

    captured = {}

    def handler(request):
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(401, content=b"unauthorized")

    with pytest.raises(UpstreamAuthFailed):
        await plat.call_platform_chat_completions(
            model_id="agnes-ai/agnes-2.5-flash",
            upstream_model="agnes-2.5-flash",
            provider="Agnes AI",
            platform_provider_id="agnes-ai",
            messages=[{"role": "user", "content": "hi"}],
            transport=httpx.MockTransport(handler),
        )
    # The secret was sent on the wire (expected), but the error path never
    # echoes it back into a message/log.
    log_text = json.dumps([rec.message for rec in caplog.records])
    assert _SYNTH_AGNES_KEY not in log_text
    assert "AGNES_API_KEY" not in log_text


@pytest.mark.asyncio
async def test_secret_absent_from_stream_events(monkeypatch):
    monkeypatch.setenv("AGNES_API_KEY", _SYNTH_AGNES_KEY)
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")

    payload = (
        b'data: {"id":"s1","model":"agnes-2.5-flash","choices":[{"delta":{"content":"a"},"finish_reason":null}]}\n\n'
        b'data: {"id":"s1","model":"agnes-2.5-flash","choices":[{"delta":{"content":"b"},"finish_reason":"stop"}]}\n\n'
        b"data: [DONE]\n\n"
    )

    def handler(request):
        return httpx.Response(200, stream=_Chunk(payload))

    events = [
        e
        async for e in plat.stream_platform_chat_completions(
            model_id="agnes-ai/agnes-2.5-flash",
            upstream_model="agnes-2.5-flash",
            provider="Agnes AI",
            platform_provider_id="agnes-ai",
            messages=[{"role": "user", "content": "hi"}],
            transport=httpx.MockTransport(handler),
        )
    ]
    assert events[-1].done is True
    assert all(_SYNTH_AGNES_KEY not in repr(e) for e in events)
    assert all("AGNES_API_KEY" not in repr(e) for e in events)


# ---------------------------------------------------------------------------
# Streaming compatibility: request translation + missing-secret fail-closed
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_platform_stream_translates_request_and_uses_secret(monkeypatch):
    monkeypatch.setenv("AGNES_API_KEY", _SYNTH_AGNES_KEY)
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    captured = {}

    payload = (
        b'data: {"id":"s1","model":"agnes-2.5-flash","choices":[{"delta":{"content":"a"},"finish_reason":null}]}\n\n'
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
            model_id="agnes-ai/agnes-2.5-flash",
            upstream_model="agnes-2.5-flash",
            provider="Agnes AI",
            platform_provider_id="agnes-ai",
            messages=[{"role": "user", "content": "hi"}],
            transport=httpx.MockTransport(handler),
        )
    ]
    assert captured["url"] == "https://apihub.agnes-ai.com/v1/chat/completions"
    assert captured["auth"] == f"Bearer {_SYNTH_AGNES_KEY}"
    assert captured["body"]["model"] == "agnes-2.5-flash"
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
                model_id="agnes-ai/agnes-2.5-flash",
                upstream_model="agnes-2.5-flash",
                provider="Agnes AI",
                platform_provider_id="agnes-ai",
                messages=[{"role": "user", "content": "hi"}],
                transport=httpx.MockTransport(handler),
            )
        ]
    assert calls["n"] == 0


# ---------------------------------------------------------------------------
# Gateway-level: explicit selection (mock), missing fails closed (live)
# ---------------------------------------------------------------------------
def test_gateway_explicit_agnes_selection_mock_mode(monkeypatch):
    monkeypatch.setenv("AGNES_API_KEY", _SYNTH_AGNES_KEY)
    monkeypatch.setenv("B14_PROVIDER_MODE", "mock")
    client = TestClient(create_app())
    response = client.post(
        "/api/pilot/v1/chat/completions",
        json={
            "model": "agnes-ai/agnes-2.5-flash",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["model"] == "agnes-2.5-flash"
    assert data["business14"]["provider"] == "Agnes AI"
    assert data["business14"]["model_route"] == "agnes-ai/agnes-2.5-flash"
    assert "AGNES_API_KEY" not in json.dumps(data)


def test_gateway_agnes_fails_closed_when_secret_missing_live(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.delenv("AGNES_API_KEY", raising=False)
    client = TestClient(create_app())
    response = client.post(
        "/api/pilot/v1/chat/completions",
        json={
            "model": "agnes-ai/agnes-2.5-flash",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "no_safe_route"
    assert "AGNES_API_KEY" not in json.dumps(response.json())


# ---------------------------------------------------------------------------
# Gateway-level: Agnes platform_secret STREAMING closure
# (stream-preview endpoint path for platform_secret providers)
# ---------------------------------------------------------------------------
_STREAM_URL = "/api/pilot/v1/chat/completions/stream-preview"


def test_stream_preview_agnes_platform_secret_streams_when_secret_present(monkeypatch):
    """platform_secret Agnes route now streams via stream-preview (mock mode)."""
    monkeypatch.setenv("AGNES_API_KEY", _SYNTH_AGNES_KEY)
    monkeypatch.setenv("B14_PROVIDER_MODE", "mock")
    client = TestClient(create_app())
    response = client.post(
        _STREAM_URL,
        json={
            "model": "agnes-ai/agnes-2.5-flash",
            "stream": True,
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    text = response.text
    # Mock platform stream emits at least one visible content delta.
    assert "Mock" in text or "delta" in text or "이것은" in text
    # Never leak the secret anywhere in the SSE body.
    assert _SYNTH_AGNES_KEY not in text
    assert "AGNES_API_KEY" not in text


def test_stream_preview_agnes_platform_secret_fails_closed_when_secret_missing(monkeypatch):
    """platform_secret Agnes streaming fails closed (zero upstream) without secret."""
    monkeypatch.setenv("B14_PROVIDER_MODE", "mock")
    monkeypatch.delenv("AGNES_API_KEY", raising=False)
    client = TestClient(create_app())
    response = client.post(
        _STREAM_URL,
        json={
            "model": "agnes-ai/agnes-2.5-flash",
            "stream": True,
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert response.status_code == 503
    body = response.json()
    assert "AGNES_API_KEY" not in json.dumps(body)


def test_stream_preview_openrouter_route_still_streams(monkeypatch):
    """OpenRouter manual route (credential_source=openrouter) still streams via
    stream-preview; the openrouter/free catalog model resolves and does not
    raise StreamNotSupported for a non-platform route."""
    monkeypatch.delenv("AGNES_API_KEY", raising=False)
    client = TestClient(create_app())
    response = client.post(
        _STREAM_URL,
        json={
            "model": "openrouter/free",
            "stream": True,
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    # Valid catalog OpenRouter model streams successfully (mock mode): the
    # gateway must route it to the OpenRouter streamer and return SSE, not
    # raise StreamNotSupported now that platform_secret is supported.
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "AGNES_API_KEY" not in response.text
    assert _SYNTH_AGNES_KEY not in response.text
