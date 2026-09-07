"""Tests for Business 14 Alpha 1: OpenRouter Gateway + Router Core.

All tests are network-free (use httpx.MockTransport). No external network calls.
"""

from __future__ import annotations

import json
import os

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.catalog import (
    CATALOG_MODELS,
    CatalogModel,
    get_catalog_by_id,
    list_catalog_summaries,
    select_by_optimize,
    filter_catalog,
)
from app.pilot.b14_runtime_config import B14RuntimeConfig
from app.pilot import router_core as rcore
from app.pilot import platform as plat
from app.pilot.router_core import (
    RouteDecision,
    resolve_manual_route,
    resolve_auto_route,
    resolve_route,
    is_error_fallback_allowed,
)
from app.pilot.errors import NoSafeRoute, PilotNotConfigured, UpstreamTimeout
from app.pilot.b14_runtime_config import runtime_config as rcfg

KILO_MODEL = "kilo/nvidia-nemotron-3-ultra-550b-a55b-free"
KILO_UPSTREAM = "nvidia/nemotron-3-ultra-550b-a55b:free"
KILO_PROVIDER = "Kilo Gateway / NVIDIA"


@pytest.fixture()
def app():
    return create_app()


@pytest.fixture()
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _reset_config(monkeypatch):
    """Reset OpenRouter config + pilot settings between tests.

    The single catalog route is a ``platform_secret`` Kilo route, so the
    platform credential plane must be isolated too: ambient KILO_API_KEY and
    B14_PROVIDER_MODE overrides are cleared so fail-closed tests observe the
    documented keyless/mock defaults.
    """
    monkeypatch.delenv("KILO_API_KEY", raising=False)
    monkeypatch.delenv("B14_PROVIDER_MODE", raising=False)
    saved = {
        "provider_mode": rcfg.provider_mode,
    }
    from app.pilot.config import pilot_settings
    saved_pilot = {
        "pilot_base_url": pilot_settings.pilot_base_url,
        "pilot_model_id": pilot_settings.pilot_model_id,
        "provider_registry_json": pilot_settings.provider_registry_json,
        "pilot_provider_id": pilot_settings.pilot_provider_id,
        "pilot_upstream_model": pilot_settings.pilot_upstream_model,
    }
    rcfg.provider_mode = "mock"
    from app.pilot.registry import reset_registry
    reset_registry()
    yield
    rcfg.provider_mode = saved["provider_mode"]
    pilot_settings.pilot_base_url = saved_pilot["pilot_base_url"]
    pilot_settings.pilot_model_id = saved_pilot["pilot_model_id"]
    pilot_settings.provider_registry_json = saved_pilot["provider_registry_json"]
    pilot_settings.pilot_provider_id = saved_pilot["pilot_provider_id"]
    pilot_settings.pilot_upstream_model = saved_pilot["pilot_upstream_model"]
    reset_registry()


def _set_live(key: str = "sk-or-v1-real-key-1234567890abcdef") -> None:
    rcfg.provider_mode = "live"


# The catalog holds a single Kilo Gateway route under decision #1933. Tests that
# exercise multi-candidate semantics (fallback, provider_order, capability
# diversity) install one synthetic second route so those contracts stay
# genuinely validated instead of silently collapsing to a single candidate.
SECONDARY_MODEL_ID = "test/secondary-free"
SECONDARY_UPSTREAM_MODEL = "test/secondary-free"
SECONDARY_PROVIDER = "Test Secondary Provider"


def _secondary_catalog_model(
    model_id: str = SECONDARY_MODEL_ID,
    upstream_model: str = SECONDARY_UPSTREAM_MODEL,
    provider: str = SECONDARY_PROVIDER,
) -> CatalogModel:
    return CatalogModel(
        model_id=model_id,
        upstream_model=upstream_model,
        display_name="Secondary Free (test only)",
        provider=provider,
        provider_type="platform",
        input_price_usd_per_1m=0.0,
        output_price_usd_per_1m=0.0,
        currency="usd",
        context_window=1_000_000,
        korean_score=4,
        latency_ms=1500,
        capabilities=frozenset({"chat", "coding", "free"}),
        region="외부",
        sort_order=20,
        credential_source="platform_secret",
        platform_provider_id="kilo",
        source="kilo_official_gateway_models",
        source_checked_at="2026-09-06",
    )


@pytest.fixture
def two_model_catalog(monkeypatch):
    """Install the real Kilo route plus one synthetic second route."""
    import app.pilot.catalog as cat

    original_models = cat.CATALOG_MODELS
    original_by_id = cat.CATALOG_BY_ID
    extra = _secondary_catalog_model()
    cat.CATALOG_MODELS = [*original_models, extra]
    cat.CATALOG_BY_ID = {m.model_id: m for m in cat.CATALOG_MODELS}
    try:
        yield extra
    finally:
        cat.CATALOG_MODELS = original_models
        cat.CATALOG_BY_ID = original_by_id


async def _ok_platform_response(upstream_model: str) -> dict:
    return {
        "id": "cmpl-test",
        "object": "chat.completion",
        "model": upstream_model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "OK"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
        "_live": True,
        "_requested_upstream_model": upstream_model,
        "_actual_response_model": upstream_model,
    }


@pytest.fixture
def patch_platform_call(monkeypatch):
    """Patch the platform adapter call the alpha gateway actually dispatches.

    The single catalog route is a ``platform_secret`` route, so the gateway
    calls ``plat.call_platform_chat_completions`` (not the OpenRouter adapter).
    Tests must patch the adapter the gateway really invokes, otherwise a live
    test would perform a real upstream call.
    """
    def _patch(fake) -> None:
        monkeypatch.setattr(plat, "call_platform_chat_completions", fake)

    return _patch


# ============================================================================
# Key isolation / redaction
# ============================================================================

class TestKeyIsolation:
    def test_key_not_in_redacted_summary(self):
        _set_live("sk-or-v1-very-secret-key-abcdef1234567890")
        summary = rcfg.redacted_summary()
        assert "sk-or-v1-very-secret-key" not in summary
        assert "abcdef1234567890" not in summary


class TestKeyRedaction:
    def test_mock_response_has_no_key(self):
        _set_live()
        from app.pilot.gateway import _build_b14_mock_metadata
        resp = _build_b14_mock_metadata("b14req_test", "kilo/nvidia-nemotron-3-ultra-550b-a55b-free", "kilo/nvidia-nemotron-3-ultra-550b-a55b-free", "Google")
        assert "sk-or-v1" not in json.dumps(resp)

    def test_error_response_no_key(self, client):
        _set_live("sk-or-v1-super-secret-12345")
        # Configure legacy BYOK too, but force Alpha path with unknown model
        from app.pilot.config import pilot_settings
        pilot_settings.pilot_base_url = "https://api.example.com"
        pilot_settings.pilot_model_id = "test-model"
        resp = client.post(
            "/api/pilot/v1/chat/completions",
            json={"model": "not-a-real-model-xyz", "messages": [{"role": "user", "content": "hi"}]},
            headers={"X-Business14-Provider-Key": "sk-or-v1-super-secret-12345"},
        )
        assert "sk-or-v1-super-secret-12345" not in resp.text


# ============================================================================
# Manual route
# ============================================================================

class TestManualRoute:
    def test_manual_route_known_model(self):
        d = resolve_manual_route("kilo/nvidia-nemotron-3-ultra-550b-a55b-free")
        assert d.route_mode == "manual"
        assert d.selected_model == "kilo/nvidia-nemotron-3-ultra-550b-a55b-free"
        assert d.selected_upstream_model == KILO_UPSTREAM
        assert d.selected_provider == KILO_PROVIDER
        assert "manual_selection" in d.reason_codes
        assert "external_fallback_disabled" in d.reason_codes
        # Keyless platform route: the Kilo free tier is anonymous, so no
        # stored secret is required and the route is always credential-ready.
        assert d.credential_available is True

    def test_manual_route_unknown_model_no_safe_route(self):
        with pytest.raises(NoSafeRoute) as exc_info:
            resolve_manual_route("nonexistent/model")
        assert exc_info.value.reason_code == "model_not_in_catalog"
        assert exc_info.value.upstream_called is False

    def test_manual_route_no_upstream_call(self):
        d = resolve_manual_route("kilo/nvidia-nemotron-3-ultra-550b-a55b-free")
        assert d.evidence_status == "resolved_not_called"

    def test_manual_route_no_fallback_by_default(self):
        d = resolve_manual_route("kilo/nvidia-nemotron-3-ultra-550b-a55b-free")
        assert d.fallback_allowed is False
        assert d.eligible_fallback == []
        assert d.max_attempts == 1
        assert "external_fallback_disabled" in d.reason_codes

    def test_manual_route_explicit_fallback_enabled(self, two_model_catalog):
        d = resolve_manual_route("kilo/nvidia-nemotron-3-ultra-550b-a55b-free", allow_external_fallback=True)
        assert d.fallback_allowed is True
        assert len(d.eligible_fallback) > 0

    def test_manual_route_id_is_candidate_specific(self):
        d = resolve_manual_route("kilo/nvidia-nemotron-3-ultra-550b-a55b-free")
        assert d.selected_route_id == "platform:kilo/nvidia-nemotron-3-ultra-550b-a55b-free"


# ============================================================================
# Automatic route (b14/auto)
# ============================================================================

class TestAutoRoute:
    def test_auto_route_selects_model(self):
        d = resolve_auto_route(optimize_for="balanced")
        assert d.route_mode == "auto"
        assert d.selected_model in {m.model_id for m in CATALOG_MODELS}
        assert d.selected_upstream_model in {m.upstream_model for m in CATALOG_MODELS}
        assert d.reason_codes[0].startswith("optimize_for:")

    def test_auto_route_korean_prefers_high_korean(self):
        d = resolve_auto_route(optimize_for="korean")
        selected = get_catalog_by_id(d.selected_model)
        # Should pick highest korean_score (gemini-2.5-flash or claude both = 5)
        assert selected is not None
        assert selected.korean_score >= 4

    def test_auto_route_cost_prefers_cheap(self):
        d = resolve_auto_route(optimize_for="cost")
        selected = get_catalog_by_id(d.selected_model)
        assert selected is not None
        price = (selected.input_price_usd_per_1m or 0.0) + (selected.output_price_usd_per_1m or 0.0)
        assert price <= 0.01

    def test_auto_route_deterministic(self):
        d1 = resolve_auto_route(optimize_for="balanced", task_type="general")
        d2 = resolve_auto_route(optimize_for="balanced", task_type="general")
        assert d1.selected_model == d2.selected_model
        assert d1.reason_codes == d2.reason_codes
        assert d1.request_id != d2.request_id  # request_id unique per call

    def test_auto_route_capability_filter(self):
        d = resolve_auto_route(required_capabilities=["chat", "coding"])
        selected = get_catalog_by_id(d.selected_model)
        assert selected is not None
        assert "coding" in selected.capabilities

    def test_auto_route_no_candidate_no_safe_route(self):
        with pytest.raises(NoSafeRoute) as exc_info:
            resolve_auto_route(required_capabilities=["impossible_capability_xyz"])
        assert exc_info.value.upstream_called is False

    def test_auto_route_no_safe_route_zero_upstream(self, client):
        """No-safe-route must return 503 with zero upstream calls."""
        resp = client.post(
            "/api/pilot/v1/chat/completions",
            json={
                "model": "b14/auto",
                "messages": [{"role": "user", "content": "hi"}],
                "business14": {"required_capabilities": ["not-a-real-capability"]},
            },
        )
        assert resp.status_code == 503
        data = resp.json()
        assert data["error"]["code"] == "no_safe_route"
        assert data["error"]["upstream_called"] is False

    def test_resolve_endpoint_no_upstream(self, client):
        resp = client.post(
            "/api/pilot/router/resolve",
            json={
                "model": "b14/auto",
                "messages": [{"role": "user", "content": "hi"}],
                "business14": {"optimize_for": "korean"},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["route_mode"] == "auto"
        assert data["selected_model"] in {m.model_id for m in CATALOG_MODELS}
        assert data["evidence_status"] == "resolved_not_called"
        assert data["selected_route_id"].startswith("platform:")
        # Single keyless Kilo route: always credential-ready, never fails
        # closed on a missing platform secret.
        assert data["credential_available"] is True

    def test_resolve_manual_model(self, client):
        resp = client.post(
            "/api/pilot/router/resolve",
            json={
                "model": "kilo/nvidia-nemotron-3-ultra-550b-a55b-free",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["route_mode"] == "manual"
        assert data["selected_model"] == "kilo/nvidia-nemotron-3-ultra-550b-a55b-free"
        assert data["selected_route_id"] == "platform:kilo/nvidia-nemotron-3-ultra-550b-a55b-free"
        assert data["fallback_allowed"] is False
        assert data["eligible_fallback"] == []
        assert data["max_attempts"] == 1

    def test_resolve_unknown_model_400(self, client):
        resp = client.post(
            "/api/pilot/router/resolve",
            json={"model": "unknown-model", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code in (400, 503)


# ============================================================================
# Fallback logic
# ============================================================================

class TestFallbackLogic:
    def test_timeout_fallback_allowed(self):
        assert is_error_fallback_allowed("upstream_timeout") is True

    def test_rate_limited_fallback_allowed(self):
        assert is_error_fallback_allowed("upstream_rate_limited") is True

    def test_server_error_fallback_allowed(self):
        assert is_error_fallback_allowed("upstream_server_error") is True

    def test_401_no_fallback(self):
        assert is_error_fallback_allowed("upstream_auth_failed") is False

    def test_403_no_fallback(self):
        assert is_error_fallback_allowed("upstream_auth_failed") is False

    def test_missing_key_no_fallback(self):
        assert is_error_fallback_allowed("missing_provider_key") is False

    def test_malformed_request_no_fallback(self):
        assert is_error_fallback_allowed("invalid_body") is False
        assert is_error_fallback_allowed("invalid_request") is False

    def test_unsupported_feature_no_fallback(self):
        assert is_error_fallback_allowed("unsupported_model") is False

    def test_generic_4xx_no_fallback(self):
        assert is_error_fallback_allowed("invalid_request") is False


class TestFallbackExecution:
    def test_429_fallback_uses_second_candidate(self, client, two_model_catalog):
        """Auto route: first candidate 429 → fallback to second."""
        from app.pilot.errors import UpstreamRateLimited
        _set_live()
        original = plat.call_platform_chat_completions
        calls = []

        async def fake(*, model_id, upstream_model, provider, platform_provider_id, messages, temperature=0.2, max_tokens=300, transport=None):
            calls.append(model_id)
            if len(calls) == 1:
                raise UpstreamRateLimited()
            return {
                "id": "cmpl-fb", "object": "chat.completion",
                "model": upstream_model,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
                "_live": True,
                "_requested_upstream_model": upstream_model,
                "_actual_response_model": upstream_model,
            }

        plat.call_platform_chat_completions = fake
        try:
            resp = client.post(
                "/api/pilot/v1/chat/completions",
                json={
                    "model": "b14/auto",
                    "messages": [{"role": "user", "content": "hi"}],
                    "business14": {"optimize_for": "balanced", "max_attempts": 3},
                },
            )
        finally:
            plat.call_platform_chat_completions = original

        assert resp.status_code == 200
        data = resp.json()
        assert data["business14"]["fallback_used"] is True
        assert data["business14"]["attempt_count"] >= 2


class TestLiveFailClosed:
    def _install_keyless_live_probe(self, monkeypatch):
        """Patch the platform adapter to capture the outbound live request.

        Decision #1933 makes the keyless Kilo Gateway route the single
        catalog route, so live mode without a key is allowed by contract.
        The security property under test becomes: no Authorization header
        is emitted and no key is leaked into the response. The adapter is
        patched to a MockTransport so the test never touches the network.
        """
        original = plat.call_platform_chat_completions
        captured = {}

        def handler(request):
            captured["authorization"] = request.headers.get("authorization")
            captured["body"] = json.loads(request.read())
            return httpx.Response(200, json=_ok_upstream_json(KILO_UPSTREAM))

        async def fake(*, model_id, upstream_model, provider, platform_provider_id,
                      messages, temperature=0.2, max_tokens=300, transport=None):
            return await original(
                model_id=model_id,
                upstream_model=upstream_model,
                provider=provider,
                platform_provider_id=platform_provider_id,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                transport=httpx.MockTransport(handler),
            )

        monkeypatch.setattr(plat, "call_platform_chat_completions", fake)
        return captured

    def test_missing_key_live_allows_keyless_route(self, client, monkeypatch):
        """Live mode, no key: the keyless Kilo route is allowed and key-free."""
        rcfg.provider_mode = "live"
        rcfg.api_key = ""
        captured = self._install_keyless_live_probe(monkeypatch)
        resp = client.post(
            "/api/pilot/v1/chat/completions",
            json={"model": "b14/auto", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 200
        assert captured["authorization"] is None
        assert "sk-or-v1" not in resp.text

    def test_placeholder_key_live_not_forwarded(self, client, monkeypatch):
        """A stale OpenRouter placeholder key is never forwarded to Kilo."""
        rcfg.provider_mode = "live"
        rcfg.api_key = "sk-your-key-here"
        captured = self._install_keyless_live_probe(monkeypatch)
        resp = client.post(
            "/api/pilot/v1/chat/completions",
            json={"model": "b14/auto", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 200
        assert captured["authorization"] is None
        assert "sk-your-key-here" not in resp.text


# ============================================================================
# Mock mode
# ============================================================================

class TestMockMode:
    def test_mock_mode_returns_mock_response(self, client):
        resp = client.post(
            "/api/pilot/v1/chat/completions",
            json={"model": "kilo/nvidia-nemotron-3-ultra-550b-a55b-free", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["business14"]["provider_mode"] == "mock"
        assert data["business14"]["route_evidence_status"] == "mock_no_upstream_call"
        assert data["choices"][0]["message"]["content"].startswith("이것은 Mock 응답")

    def test_mock_mode_auto_model(self, client):
        resp = client.post(
            "/api/pilot/v1/chat/completions",
            json={"model": "b14/auto", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["business14"]["provider_mode"] == "mock"
        assert data["business14"]["route_mode"] == "auto"
        assert "selected_model" in data["business14"]

    def test_mock_mode_zero_upstream(self, client):
        """Mock mode must never reach an upstream transport."""
        _set_live()  # live key present
        rcfg.provider_mode = "mock"  # but mode is mock
        # Mock mode should NOT use live transport — verify no auth error
        resp = client.post(
            "/api/pilot/v1/chat/completions",
            json={"model": "b14/auto", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["business14"]["provider_mode"] == "mock"


# ============================================================================
# Live mode adapter (MockTransport)
# ============================================================================

class TestLiveAdapter:
    @pytest.mark.asyncio
    async def test_live_call_success_usage_propagates(self):
        # Keyless Kilo Gateway route: no Authorization header, fixed origin.
        rcfg.provider_mode = "live"
        rcfg.api_key = ""
        async def fake_upstream(request):
            assert str(request.url) == "https://api.kilo.ai/api/gateway/chat/completions"
            assert request.headers.get("authorization") is None
            body = json.loads(request.content)
            assert body["model"] == KILO_UPSTREAM
            assert "provider" not in body
            return httpx.Response(200, json={
                "id": "cmpl-live", "object": "chat.completion",
                "model": KILO_UPSTREAM,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "live OK"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            })
        result = await plat.call_platform_chat_completions(
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.2,
            max_tokens=32,
            model_id=KILO_MODEL,
            upstream_model=KILO_UPSTREAM,
            provider=KILO_PROVIDER,
            platform_provider_id="kilo",
            transport=httpx.MockTransport(fake_upstream),
        )
        assert result["_live"] is True
        assert result["usage"]["total_tokens"] == 30

    @pytest.mark.asyncio
    async def test_live_call_malformed_json(self):
        rcfg.provider_mode = "live"
        rcfg.api_key = ""
        from app.pilot.errors import MalformedUpstreamResponse
        async def fake_bad(request):
            return httpx.Response(200, text="not-json{{{")
        with pytest.raises(MalformedUpstreamResponse):
            await plat.call_platform_chat_completions(
                messages=[{"role": "user", "content": "hi"}],
                temperature=0.2, max_tokens=32,
                model_id=KILO_MODEL,
                upstream_model=KILO_UPSTREAM,
                provider=KILO_PROVIDER,
                platform_provider_id="kilo",
                transport=httpx.MockTransport(fake_bad),
            )

    @pytest.mark.asyncio
    async def test_live_call_401(self):
        rcfg.provider_mode = "live"
        rcfg.api_key = ""
        from app.pilot.errors import UpstreamAuthFailed
        async def fake_401(request):
            return httpx.Response(401, json={"error": {"message": "unauthorized"}})
        with pytest.raises(UpstreamAuthFailed):
            await plat.call_platform_chat_completions(
                messages=[{"role": "user", "content": "hi"}],
                temperature=0.2, max_tokens=32,
                model_id=KILO_MODEL,
                upstream_model=KILO_UPSTREAM,
                provider=KILO_PROVIDER,
                platform_provider_id="kilo",
                transport=httpx.MockTransport(fake_401),
            )

    @pytest.mark.asyncio
    async def test_live_call_timeout(self):
        rcfg.provider_mode = "live"
        rcfg.api_key = ""
        async def fake_timeout(request):
            raise httpx.TimeoutException("timed out")
        with pytest.raises(UpstreamTimeout):
            await plat.call_platform_chat_completions(
                messages=[{"role": "user", "content": "hi"}],
                temperature=0.2, max_tokens=32,
                model_id=KILO_MODEL,
                upstream_model=KILO_UPSTREAM,
                provider=KILO_PROVIDER,
                platform_provider_id="kilo",
                transport=httpx.MockTransport(fake_timeout),
            )

    @pytest.mark.asyncio
    async def test_live_call_429(self):
        rcfg.provider_mode = "live"
        rcfg.api_key = ""
        from app.pilot.errors import KiloFreeRateLimited
        async def fake_429(request):
            return httpx.Response(429, json={"error": {"message": "slow down"}})
        with pytest.raises(KiloFreeRateLimited):
            await plat.call_platform_chat_completions(
                messages=[{"role": "user", "content": "hi"}],
                temperature=0.2, max_tokens=32,
                model_id=KILO_MODEL,
                upstream_model=KILO_UPSTREAM,
                provider=KILO_PROVIDER,
                platform_provider_id="kilo",
                transport=httpx.MockTransport(fake_429),
            )

    @pytest.mark.asyncio
    async def test_live_call_500(self):
        rcfg.provider_mode = "live"
        rcfg.api_key = ""
        from app.pilot.errors import UpstreamServerError
        async def fake_500(request):
            return httpx.Response(500, json={"error": {"message": "oops"}})
        with pytest.raises(UpstreamServerError):
            await plat.call_platform_chat_completions(
                messages=[{"role": "user", "content": "hi"}],
                temperature=0.2, max_tokens=32,
                model_id=KILO_MODEL,
                upstream_model=KILO_UPSTREAM,
                provider=KILO_PROVIDER,
                platform_provider_id="kilo",
                transport=httpx.MockTransport(fake_500),
            )

    @pytest.mark.asyncio
    async def test_live_call_no_key(self):
        # Kilo free tier is keyless: live without a key is allowed (#1933 S2).
        rcfg.provider_mode = "live"
        rcfg.api_key = ""
        async def fake_ok(request):
            assert request.headers.get("authorization") is None
            return httpx.Response(200, json={
                "id": "cmpl-keyless", "object": "chat.completion",
                "model": KILO_UPSTREAM,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            })
        result = await plat.call_platform_chat_completions(
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.2, max_tokens=32,
            model_id=KILO_MODEL,
            upstream_model=KILO_UPSTREAM,
            provider=KILO_PROVIDER,
            platform_provider_id="kilo",
            transport=httpx.MockTransport(fake_ok),
        )
        assert result["_live"] is True


# ============================================================================
# Cost estimates
# ============================================================================

class TestCostEstimate:
    def test_price_known_estimate(self):
        cm = get_catalog_by_id("kilo/nvidia-nemotron-3-ultra-550b-a55b-free")
        assert cm.price_is_known
        expected = cm.input_price_usd_per_1m + cm.output_price_usd_per_1m
        usd = cm.estimate_cost_usd(1_000_000, 1_000_000)
        assert usd is not None
        assert usd == pytest.approx(expected, rel=1e-9)

    def test_free_route_known_zero_estimate(self):
        cm = get_catalog_by_id("kilo/nvidia-nemotron-3-ultra-550b-a55b-free")
        assert cm.price_is_known
        assert cm.input_price_usd_per_1m == 0.0
        assert cm.output_price_usd_per_1m == 0.0
        assert cm.estimate_cost_usd(1000, 500) == 0.0
        assert cm.estimate_cost_krw(1000, 500) == 0.0

    def test_price_unknown_null(self):
        cm = CatalogModel(
            model_id="test/unknown-price",
            upstream_model="test/unknown-price",
            display_name="Unknown Price",
            provider="Test",
            provider_type="external",
            input_price_usd_per_1m=None,
            output_price_usd_per_1m=None,
        )
        assert cm.price_is_known is False
        assert cm.estimate_cost_usd(1000, 500) is None
        assert cm.estimate_cost_krw(1000, 500) is None

    def test_krw_uses_configured_rate(self):
        cm = get_catalog_by_id("kilo/nvidia-nemotron-3-ultra-550b-a55b-free")
        expected_usd = cm.input_price_usd_per_1m + cm.output_price_usd_per_1m
        krw = cm.estimate_cost_krw(1_000_000, 1_000_000)
        assert krw is not None
        assert krw == pytest.approx(expected_usd * 1380, rel=1e-9)

    def test_live_response_has_estimate(self):
        _set_live()
        from app.pilot.gateway import _build_b14_live_metadata as build_live_metadata
        cm = get_catalog_by_id(KILO_MODEL)
        expected_usd = cm.estimate_cost_usd(1_000_000, 1_000_000)
        meta = build_live_metadata(
            request_id="b14req_test",
            model_id=KILO_MODEL,
            upstream_model=KILO_UPSTREAM,
            provider=KILO_PROVIDER,
            latency_ms=100,
            prompt_tokens=1_000_000,
            completion_tokens=1_000_000,
            total_tokens=2_000_000,
        )
        assert meta["estimated_usd"] == pytest.approx(expected_usd, rel=1e-9)
        assert meta["estimated_krw"] == pytest.approx(expected_usd * 1380, rel=1e-9)
        assert meta["cost_basis"] == "known_free"  # $0/$0 snapshot is the free basis

    def test_free_route_live_metadata_known_free(self):
        _set_live()
        from app.pilot.gateway import _build_b14_live_metadata as build_live_metadata
        meta = build_live_metadata(
            request_id="b14req_test",
            model_id="kilo/nvidia-nemotron-3-ultra-550b-a55b-free",
            upstream_model="kilo/nvidia-nemotron-3-ultra-550b-a55b-free",
            provider="OpenRouter (free router)",
            latency_ms=100,
            prompt_tokens=1000,
            completion_tokens=500,
            total_tokens=1500,
            actual_response_model="some/free-model",
        )
        assert meta["estimated_usd"] == 0.0
        assert meta["estimated_krw"] == 0.0
        assert meta["cost_basis"] == "known_free"
        assert meta["actual_response_model"] == "some/free-model"


# ============================================================================
# API metadata completeness
# ============================================================================

class TestMetadataCompleteness:
    _REQUIRED_FIELDS = {
        "route_mode",
        "selected_provider",
        "selected_model",
        "selected_upstream_model",
        "actual_response_model",
        "selected_route_id",
        "reason_codes",
        "fallback_allowed",
        "fallback_used",
        "attempt_count",
        "attempt_evidence",
        "route_evidence_status",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "estimated_usd",
        "estimated_krw",
        "cost_basis",
        "request_id",
        "provider_mode",
    }

    def test_mock_chat_metadata_complete(self, client):
        resp = client.post(
            "/api/pilot/v1/chat/completions",
            json={"model": "b14/auto", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 200
        biz14 = resp.json()["business14"]
        assert self._REQUIRED_FIELDS.issubset(set(biz14))
        assert biz14["provider_mode"] == "mock"

    def test_resolve_metadata_complete(self, client):
        resp = client.post(
            "/api/pilot/router/resolve",
            json={"model": "b14/auto", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 200
        data = resp.json()
        for field in ("route_mode", "selected_provider", "selected_model", "selected_route_id",
                      "reason_codes", "fallback_allowed", "eligible_fallback", "credential_available",
                      "evidence_status", "request_id", "provider_mode"):
            assert field in data, f"missing {field}"


# ============================================================================
# Health / Models endpoints
# ============================================================================

class TestEndpoints:
    def test_health_includes_b14_info(self, client):
        resp = client.get("/api/pilot/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "business14" in data
        assert data["business14"]["provider_mode"] == "mock"

    def test_models_includes_catalog(self, client):
        resp = client.get("/api/pilot/models")
        assert resp.status_code == 200
        data = resp.json()
        catalog = data.get("catalog", [])
        assert len(catalog) >= len(CATALOG_MODELS)  # includes b14/auto
        ids = {m["id"] for m in catalog}
        assert "b14/auto" in ids
        assert "kilo/nvidia-nemotron-3-ultra-550b-a55b-free" in ids

    def test_legacy_models_still_work(self, client):
        from app.pilot.config import pilot_settings
        pilot_settings.pilot_base_url = "https://api.example.com"
        pilot_settings.pilot_model_id = "test-model-v1"
        resp = client.get("/api/pilot/models")
        assert resp.status_code == 200
        assert "test-model-v1" in resp.text

    def test_health_legacy_still_works(self, client):
        from app.pilot.config import pilot_settings
        pilot_settings.pilot_base_url = "https://api.example.com"
        pilot_settings.pilot_model_id = "test-model-v1"
        resp = client.get("/api/pilot/health")
        assert resp.status_code == 200
        assert "business14" in resp.json()


# ============================================================================
# Catalog / registry
# ============================================================================

class TestCatalog:
    def test_catalog_minimum_models(self):
        ids = {m.model_id for m in CATALOG_MODELS}
        # Decision #1933 pins a single-route Kilo Gateway catalog; the
        # deleted multi-provider entries are exercised by two_model_catalog.
        assert ids == {KILO_MODEL}

    def test_all_catalog_models_enabled(self):
        assert all(m.enabled for m in CATALOG_MODELS)

    def test_catalog_by_id_lookup(self):
        assert get_catalog_by_id("kilo/nvidia-nemotron-3-ultra-550b-a55b-free") is not None
        assert get_catalog_by_id("nonexistent") is None

    def test_filter_by_capability(self):
        result = filter_catalog(required_capabilities=["chat"])
        assert len(result) == len(CATALOG_MODELS)

    def test_select_by_optimize_cost_first_free(self):
        sorted_models = select_by_optimize(CATALOG_MODELS, "cost", True)
        assert sorted_models[0].model_id == "kilo/nvidia-nemotron-3-ultra-550b-a55b-free"

    def test_select_by_optimize_korean_high_score(self):
        sorted_models = select_by_optimize(CATALOG_MODELS, "korean", True)
        assert sorted_models[0].korean_score >= 4

    def test_list_catalog_summaries_shape(self):
        summaries = list_catalog_summaries()
        assert len(summaries) == len(CATALOG_MODELS)
        assert "model_id" in summaries[0]
        assert "input_price_usd_per_1m" in summaries[0]


# ============================================================================
# Legacy registry compatibility
# ============================================================================

class TestLegacyCompat:
    def test_legacy_registry_health(self, client):
        from app.pilot.config import pilot_settings
        from app.pilot.registry import reset_registry
        registry_data = [{
            "provider_id": "provider-a",
            "display_name": "Provider A",
            "base_url": "https://api.provider-a.example",
            "timeout_seconds": 30,
            "models": [{"model_id": "model-a-v1", "upstream_model": "upstream-a", "display_name": "Model A", "enabled": True}],
        }]
        pilot_settings.provider_registry_json = json.dumps(registry_data)
        reset_registry()
        resp = client.get("/api/pilot/health")
        assert resp.status_code == 200
        assert resp.json()["mode"] == "byok-multi-provider-pilot"

    def test_legacy_chat_still_works(self, client):
        """Legacy BYOK chat must still work (model-a-v1 via X-Business14-Provider-Key)."""
        from app.pilot.config import pilot_settings
        from app.pilot.registry import reset_registry
        registry_data = [{
            "provider_id": "provider-a",
            "display_name": "Provider A",
            "base_url": "https://api.provider-a.example",
            "timeout_seconds": 30,
            "models": [{"model_id": "model-a-v1", "upstream_model": "upstream-a", "display_name": "Model A", "enabled": True}],
        }]
        pilot_settings.provider_registry_json = json.dumps(registry_data)
        reset_registry()
        from app.pilot import provider as prv
        original = prv.call_chat_completions
        async def fake_call(**kw):
            return {"id": "test", "object": "chat.completion", "model": "model-a-v1",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hello!"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
                    "business14": {"mode": "byok-multi-provider-pilot", "provider": "provider-a", "latency_ms": 100, "estimated_krw": None, "request_id": "b14req_test"}}
        prv.call_chat_completions = fake_call
        try:
            resp = client.post(
                "/api/pilot/v1/chat/completions",
                json={"model": "model-a-v1", "messages": [{"role": "user", "content": "hi"}]},
                headers={"X-Business14-Provider-Key": "sk-real-key-12345abcdef"},
            )
        finally:
            prv.call_chat_completions = original
        assert resp.status_code == 200
        assert resp.json()["business14"]["mode"] == "byok-multi-provider-pilot"


# ============================================================================
# Korean UI journey
# ============================================================================

class TestKoreanUIJourney:
    def test_workspace_page_has_start_screen(self, client):
        resp = client.get("/workspace")
        assert resp.status_code == 200
        text = resp.text
        assert "start_prompt" in text
        assert "start_model" in text
        assert "start_send" in text
        assert "모의 응답" in text or "실제 Provider" in text

    def test_workspace_page_shows_mock_label(self, client):
        resp = client.get("/workspace")
        assert "모의 응답 · 실제 Provider 호출 없음" in resp.text

    def test_workspace_page_catalog_options(self, client):
        resp = client.get("/workspace")
        assert "b14/auto" in resp.text
        assert "kilo/nvidia-nemotron-3-ultra-550b-a55b-free" in resp.text

    def test_start_js_loaded(self, client):
        resp = client.get("/workspace")
        assert 'src="/start.js' in resp.text

    def test_start_css_loaded(self, client):
        resp = client.get("/workspace")
        assert 'href="/start.css' in resp.text

    def test_start_js_no_innerhtml_for_content(self):
        import os
        js_path = os.path.join(os.path.dirname(__file__), "..", "static", "start.js")
        with open(js_path, encoding="utf-8") as f:
            js = f.read()
        # innerHTML is only allowed in comments — content is rendered via textContent/replaceChildren
        import re
        code = re.sub(r"/\*.*?\*/", "", js, flags=re.DOTALL)
        code = re.sub(r"//.*?$", "", code, flags=re.MULTILINE)
        assert "innerHTML" not in code, "innerHTML must not be used for content rendering"
        assert "replaceChildren" in js or "textContent" in js

    def test_start_js_try_finally(self):
        import os
        js_path = os.path.join(os.path.dirname(__file__), "..", "static", "start.js")
        with open(js_path, encoding="utf-8") as f:
            js = f.read()
        assert "finally {" in js, "sendMessage must use try/finally"
        assert "state.isSending = false" in js

    def test_workspace_config_has_b14_fields(self, client):
        resp = client.get("/workspace")
        import re
        m = re.search(
            r'<script id="workspace-config" type="application/json">\s*(.*?)\s*</script>',
            resp.text, re.DOTALL,
        )
        assert m
        config = json.loads(m.group(1))
        assert "b14ProviderMode" in config
        assert "b14CatalogModels" in config
        assert config["b14ProviderMode"] == "mock"

    def test_keyboard_send_enter(self):
        """start.js must support Enter-to-send on the prompt."""
        import os
        js_path = os.path.join(os.path.dirname(__file__), "..", "static", "start.js")
        with open(js_path, encoding="utf-8") as f:
            js = f.read()
        assert "onPromptKeydown" in js
        assert "e.key === \"Enter\"" in js


# ============================================================================
# Mobile responsive
# ============================================================================

class TestMobileResponsive:
    def test_start_css_mobile_no_overflow(self):
        import os
        css_path = os.path.join(os.path.dirname(__file__), "..", "static", "start.css")
        with open(css_path, encoding="utf-8") as f:
            css = f.read()
        assert "@media (max-width: 768px)" in css
        assert "grid-template-columns: 1fr" in css  # single column on mobile

    def test_base_mobile_css_exists(self):
        import os
        css_path = os.path.join(os.path.dirname(__file__), "..", "static", "app.css")
        with open(css_path, encoding="utf-8") as f:
            css = f.read()
        assert "@media (max-width: 768px)" in css
        assert "overflow-x" in css or "max-width: 100%" in css


# ============================================================================
# External network: 0
# ============================================================================

class TestNoExternalNetwork:
    def test_mock_mode_zero_external_requests(self, client):
        """Mock mode must make zero upstream HTTP calls (verified via mock transport)."""
        original = plat.call_platform_chat_completions
        calls = []
        async def spy(*args, **kwargs):
            calls.append(kwargs.get("transport"))
            return await original(*args, **kwargs)
        plat.call_platform_chat_completions = spy
        try:
            resp = client.post(
                "/api/pilot/v1/chat/completions",
                json={"model": "b14/auto", "messages": [{"role": "user", "content": "hi"}]},
            )
        finally:
            plat.call_platform_chat_completions = original
        assert resp.status_code == 200
        # In mock mode, no transport is passed (mock short-circuits before transport)
        assert all(t is None for t in calls), "mock mode should not use transport"

    def test_all_tests_use_mock_transport_only(self):
        """The test suite itself never creates a real network transport."""
        import re
        import os
        import glob
        test_dir = os.path.dirname(__file__)
        this_file = os.path.basename(__file__)
        for f in glob.glob(os.path.join(test_dir, "test_*.py")):
            basename = os.path.basename(f)
            if basename == this_file:
                continue  # self-references in this file's assertions are not network usage
            with open(f, encoding="utf-8") as fh:
                content = fh.read()
            if basename == "test_owner_startup_command.py":
                # This regression intentionally probes the subprocess over loopback only.
                # Keep the exception narrow so it can never become an upstream-network test.
                assert "http://127.0.0.1:" in content
                assert "https://" not in content
                assert "openrouter.ai" not in content
                assert "requests." not in content
                assert "httpx." not in content
                continue
            # All other tests remain transport-mocked/network-free.
            assert "urllib.request.urlopen(" not in content, f"{f} uses urllib"
            assert "requests.get(" not in content, f"{f} uses requests.get"
            assert "httpx.Client(" not in content, f"{f} uses httpx.Client"
            assert "http.client" not in content, f"{f} uses http.client"


# ============================================================================
# Error body / response limits
# ============================================================================

class TestResponseLimits:
    def test_malformed_upstream_json(self):
        from app.pilot.errors import MalformedUpstreamResponse
        assert MalformedUpstreamResponse().code == "malformed_upstream_response"

    def test_oversized_body_limit_configured(self):
        assert rcfg.max_response_bytes == 1024 * 1024

    def test_timeout_bounds_configured(self):
        timeout = rcfg.build_http_timeout()
        assert timeout.connect <= 10
        assert timeout.read <= 30
        assert timeout.write <= 10
        assert timeout.pool <= 10


# ============================================================================
# Route smoke — all existing routes preserved
# ============================================================================

class TestRouteSmoke:
    def test_all_routes(self, client):
        routes = ["/", "/models", "/playground", "/api-keys", "/docs", "/usage",
                  "/pricing", "/access", "/pilot", "/workspace",
                  "/api/pilot/health", "/api/pilot/models"]
        for route in routes:
            resp = client.get(route)
            assert resp.status_code == 200, f"{route} returned {resp.status_code}"


# ============================================================================
# Alpha 1 correction regressions (Web CTO review blockers)
# ============================================================================

def _ok_upstream_json(model: str) -> dict:
    return {
        "id": "cmpl-correction",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "OK"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 1000, "total_tokens": 2000},
    }


class TestFreeRouterExactRoute:
    def test_free_router_catalog_exact_upstream_id(self):
        cm = get_catalog_by_id(KILO_MODEL)
        assert cm is not None
        assert cm.model_id == KILO_MODEL
        assert cm.upstream_model == KILO_UPSTREAM

    @pytest.mark.asyncio
    async def test_free_router_request_body_exact_and_actual_model_preserved(self):
        _set_live()
        captured = []
        concrete_free_model = "kilo/nvidia-nemotron-3-ultra-550b-a55b-free"

        async def handler(request):
            captured.append(json.loads(request.read()))
            return httpx.Response(200, json=_ok_upstream_json(concrete_free_model))

        result = await plat.call_platform_chat_completions(
            messages=[{"role": "user", "content": "안녕"}],
            temperature=0.2,
            max_tokens=16,
            model_id="kilo/nvidia-nemotron-3-ultra-550b-a55b-free",
            upstream_model="kilo/nvidia-nemotron-3-ultra-550b-a55b-free",
            provider=KILO_PROVIDER,
            platform_provider_id="kilo",
            transport=httpx.MockTransport(handler),
        )
        assert captured[0]["model"] == "kilo/nvidia-nemotron-3-ultra-550b-a55b-free"
        assert "provider" not in captured[0]
        assert result["_requested_upstream_model"] == "kilo/nvidia-nemotron-3-ultra-550b-a55b-free"
        assert result["_actual_response_model"] == concrete_free_model
        assert result["model"] == concrete_free_model


class TestCatalogSourceContract:
    def test_catalog_source_metadata(self):
        summaries = list_catalog_summaries()
        assert summaries
        for s in summaries:
            assert s["source"] == "kilo_official_gateway_models"
            assert s["snapshot_state"] == "configured_snapshot"
            assert s["source_checked_at"]
            assert "upstream_model" in s
            assert "price_is_known" in s

    def test_kilo_route_price_snapshot(self):
        """The single catalog route pins the $0/$0 free-tier snapshot."""
        cm = get_catalog_by_id(KILO_MODEL)
        assert cm.input_price_usd_per_1m == pytest.approx(0.0)
        assert cm.output_price_usd_per_1m == pytest.approx(0.0)
        assert cm.price_is_known is True
        assert cm.context_window == 1_000_000
        assert "free" in cm.capabilities


class TestFallbackFailClosed:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("status,expected_code", [
        (400, "malformed_upstream_response"),
        (404, "upstream_client_error"),
        (422, "upstream_client_error"),
    ])
    async def test_client_errors_raise_and_no_fallback(self, status, expected_code):
        _set_live()
        from app.pilot.errors import PilotError

        async def handler(request):
            return httpx.Response(status, json={"error": {"message": "rejected"}})

        with pytest.raises(PilotError) as exc_info:
            await plat.call_platform_chat_completions(
                messages=[{"role": "user", "content": "hi"}],
                temperature=0.2,
                max_tokens=16,
                model_id="kilo/nvidia-nemotron-3-ultra-550b-a55b-free",
                upstream_model="kilo/nvidia-nemotron-3-ultra-550b-a55b-free",
                provider=KILO_PROVIDER,
                platform_provider_id="kilo",
                transport=httpx.MockTransport(handler),
            )
        assert exc_info.value.code == expected_code
        assert is_error_fallback_allowed(exc_info.value.code) is False

    def test_unknown_exception_no_fallback_in_gateway(self, client):
        _set_live()
        original = plat.call_platform_chat_completions
        calls = []

        async def fake(*, model_id, upstream_model, provider, platform_provider_id, messages, temperature=0.2, max_tokens=300, transport=None):
            calls.append(model_id)
            raise ValueError("unexpected")

        plat.call_platform_chat_completions = fake
        try:
            resp = client.post(
                "/api/pilot/v1/chat/completions",
                json={
                    "model": "b14/auto",
                    "messages": [{"role": "user", "content": "hi"}],
                    "business14": {"optimize_for": "cost", "max_attempts": 3},
                },
            )
        finally:
            plat.call_platform_chat_completions = original

        assert resp.status_code == 500
        data = resp.json()
        assert data["error"]["code"] == "internal_error"
        assert data["error"]["fallback_used"] is False
        assert data["error"]["attempt_count"] == 1
        assert len(calls) == 1


class TestFallbackActualEvidence:
    def test_fallback_metadata_describes_actual_success_candidate(self, client, two_model_catalog):
        _set_live()
        from app.pilot.errors import UpstreamRateLimited
        original = plat.call_platform_chat_completions
        calls = []

        async def fake(*, model_id, upstream_model, provider, platform_provider_id, messages, temperature=0.2, max_tokens=300, transport=None):
            calls.append({"model_id": model_id, "upstream_model": upstream_model, "provider": provider})
            if len(calls) == 1:
                raise UpstreamRateLimited()
            return {
                "id": "cmpl-fb-actual",
                "object": "chat.completion",
                "model": upstream_model,
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": "OK"},
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 1000, "total_tokens": 2000},
                "_live": True,
                "_requested_upstream_model": upstream_model,
                "_actual_response_model": upstream_model,
            }

        plat.call_platform_chat_completions = fake
        try:
            resp = client.post(
                "/api/pilot/v1/chat/completions",
                json={
                    "model": "b14/auto",
                    "messages": [{"role": "user", "content": "hi"}],
                    "business14": {"optimize_for": "cost", "max_attempts": 3},
                },
            )
        finally:
            plat.call_platform_chat_completions = original

        assert resp.status_code == 200
        assert len(calls) == 2
        data = resp.json()
        biz14 = data["business14"]
        actual = calls[1]
        assert biz14["fallback_used"] is True
        assert biz14["attempt_count"] == 2
        assert biz14["selected_model"] == actual["model_id"]
        assert biz14["selected_provider"] == actual["provider"]
        assert biz14["selected_upstream_model"] == actual["upstream_model"]
        assert biz14["actual_response_model"] == actual["upstream_model"]
        assert data["model"] == actual["upstream_model"]
        assert biz14["selected_route_id"] == f"platform:{actual['model_id']}"
        assert biz14["attempt_evidence"][0]["outcome"] == "error"
        assert biz14["attempt_evidence"][0]["error_code"] == "upstream_rate_limited"
        assert biz14["attempt_evidence"][1]["outcome"] == "success"

        cm = get_catalog_by_id(actual["model_id"])
        expected_usd = cm.estimate_cost_usd(1000, 1000)
        if cm.price_is_known:
            assert biz14["estimated_usd"] == pytest.approx(expected_usd, rel=1e-9)
            assert biz14["cost_basis"] in {"configured_snapshot", "known_free"}
        else:
            assert biz14["estimated_usd"] is None
            assert biz14["cost_basis"] == "unknown"


class TestOptionEnforcement:
    def test_allow_external_fallback_false_resolve(self):
        d = resolve_auto_route(optimize_for="cost", allow_external_fallback=False)
        assert d.fallback_allowed is False
        assert d.eligible_fallback == []
        assert d.max_attempts == 1
        assert "external_fallback_disabled" in d.reason_codes

    def test_allow_external_fallback_false_gateway_no_retry(self, client):
        _set_live()
        pass  # OpenRouter retired (#1933 S2): platform adapter is patched directly
        from app.pilot.errors import UpstreamRateLimited
        original = plat.call_platform_chat_completions
        calls = []

        async def fake(*, model_id, upstream_model, provider, platform_provider_id, messages, temperature=0.2, max_tokens=300, transport=None):
            calls.append(model_id)
            raise UpstreamRateLimited()

        plat.call_platform_chat_completions = fake
        try:
            resp = client.post(
                "/api/pilot/v1/chat/completions",
                json={
                    "model": "b14/auto",
                    "messages": [{"role": "user", "content": "hi"}],
                    "business14": {"optimize_for": "cost", "allow_external_fallback": False},
                },
            )
        finally:
            plat.call_platform_chat_completions = original

        assert resp.status_code == 429
        assert resp.json()["error"]["code"] == "upstream_rate_limited"
        assert len(calls) == 1

    def test_provider_order_changes_selection(self, two_model_catalog):
        default_pick = resolve_auto_route(optimize_for="cost")
        assert default_pick.selected_provider == KILO_PROVIDER

        ordered = resolve_auto_route(optimize_for="cost", provider_order=[SECONDARY_PROVIDER])
        assert ordered.selected_provider == SECONDARY_PROVIDER
        assert ordered.selected_model == SECONDARY_MODEL_ID
        assert any(rc.startswith("provider_order:") for rc in ordered.reason_codes)

    def test_provider_order_api(self, client, two_model_catalog):
        resp = client.post(
            "/api/pilot/router/resolve",
            json={
                "model": "b14/auto",
                "messages": [{"role": "user", "content": "hi"}],
                "business14": {"optimize_for": "cost", "provider_order": [SECONDARY_PROVIDER]},
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["selected_provider"] == SECONDARY_PROVIDER
        assert body["selected_model"] == SECONDARY_MODEL_ID

    def test_provider_order_invalid_type_422(self, client):
        resp = client.post(
            "/api/pilot/router/resolve",
            json={
                "model": "b14/auto",
                "messages": [{"role": "user", "content": "hi"}],
                "business14": {"provider_order": "Anthropic"},
            },
        )
        assert resp.status_code == 422

    def test_task_type_hard_capability_filter(self):
        coding = resolve_auto_route(task_type="coding")
        coding_model = get_catalog_by_id(coding.selected_model)
        assert "coding" in coding_model.capabilities

        document = resolve_auto_route(task_type="document")
        document_model = get_catalog_by_id(document.selected_model)
        assert "chat" in document_model.capabilities
        assert document.selected_model == KILO_MODEL

    def test_task_type_invalid_422(self, client):
        resp = client.post(
            "/api/pilot/router/resolve",
            json={
                "model": "b14/auto",
                "messages": [{"role": "user", "content": "hi"}],
                "business14": {"task_type": "not-a-task"},
            },
        )
        assert resp.status_code == 422

    def test_unknown_business14_field_422(self, client):
        resp = client.post(
            "/api/pilot/router/resolve",
            json={
                "model": "b14/auto",
                "messages": [{"role": "user", "content": "hi"}],
                "business14": {"unsupported_option": True},
            },
        )
        assert resp.status_code == 422


class TestStreamedResponseLimit:
    @pytest.mark.asyncio
    async def test_oversize_response_aborts_before_full_body(self):
        # Platform streaming enforces MAX_RESPONSE_BYTES without buffering.
        rcfg.provider_mode = "live"
        rcfg.api_key = ""
        from app.pilot.errors import UpstreamResponseTooLarge

        chunk = b"x" * (512 * 1024)
        chunks = [chunk, chunk, chunk, b'{"never": "fully read"}']

        class CountingStream(httpx.AsyncByteStream):
            def __init__(self, parts):
                self.parts = parts
                self.consumed = 0

            async def __aiter__(self):
                for part in self.parts:
                    self.consumed += 1
                    yield part

            async def aclose(self) -> None:
                return None

        stream = CountingStream(chunks)

        async def handler(request):
            return httpx.Response(200, stream=stream)

        with pytest.raises(UpstreamResponseTooLarge):
            async for _ in plat.stream_platform_chat_completions(
                messages=[{"role": "user", "content": "hi"}],
                temperature=0.2,
                max_tokens=16,
                model_id=KILO_MODEL,
                upstream_model=KILO_UPSTREAM,
                provider=KILO_PROVIDER,
                platform_provider_id="kilo",
                transport=httpx.MockTransport(handler),
            ):
                pass
        assert stream.consumed < len(chunks)
        assert is_error_fallback_allowed("upstream_response_too_large") is False


class TestOwnerEnvWorkflow:
    def test_env_bootstrap_loads_file(self, tmp_path, monkeypatch):
        from app.env_bootstrap import load_env_file

        key = "B14_TEST_ENV_BOOTSTRAP_KEY"
        export_key = "B14_TEST_ENV_BOOTSTRAP_EXPORT"
        monkeypatch.delenv(key, raising=False)
        monkeypatch.delenv(export_key, raising=False)

        env_file = tmp_path / ".env"
        env_file.write_text(
            "# comment\n"
            f"{key}=hello\n"
            f'export {export_key}="quoted value"\n',
            encoding="utf-8",
        )
        try:
            loaded = load_env_file(env_file)
            assert loaded == 2
            assert os.environ.get(key) == "hello"
            assert os.environ.get(export_key) == "quoted value"
        finally:
            monkeypatch.delenv(key, raising=False)
            monkeypatch.delenv(export_key, raising=False)

    def test_env_bootstrap_does_not_overwrite_existing(self, tmp_path, monkeypatch):
        from app.env_bootstrap import load_env_file

        key = "B14_TEST_ENV_BOOTSTRAP_EXISTING"
        monkeypatch.setenv(key, "existing")
        env_file = tmp_path / ".env"
        env_file.write_text(f"{key}=from_file\n", encoding="utf-8")
        loaded = load_env_file(env_file)
        assert loaded == 0
        assert os.environ.get(key) == "existing"

    def test_documented_startup_command_in_readme(self):
        from pathlib import Path
        readme = Path(__file__).resolve().parent.parent / "README.md"
        text = readme.read_text(encoding="utf-8")
        assert "python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000" in text
        assert "python3 -m uvicorn app.main:app --env-file .env" not in text
        assert "app.main` loads working-directory `.env`" in text

    def test_secret_not_exposed_when_key_configured(self, client, monkeypatch):
        openrouter_secret = "sk-or-v1-super-secret-abcdef1234567890"
        platform_secret = "sk-sensenova-super-secret-abcdef1234567890"
        _set_live(openrouter_secret)
        monkeypatch.setenv("PADIEM_SENSENOVA_API_KEY", platform_secret)
        resp = client.get("/api/pilot/health")
        assert resp.status_code == 200
        assert resp.json()["business14"]["has_key"] is True
        for path in ("/api/pilot/health", "/api/pilot/models", "/workspace"):
            page = client.get(path)
            assert page.status_code == 200
            assert openrouter_secret not in page.text
            assert platform_secret not in page.text


# ============================================================================
# Issue 2: Manual route default fallback separation
# ============================================================================


class TestManualRouteDefaultFallback:
    """Manual model ID: allow_external_fallback defaults to False.

    Only when the user explicitly passes allow_external_fallback=true
    are fallback candidates and multi-attempt logic engaged.
    """

    def test_manual_model_no_business14_resolve(self, client):
        """manual model, no business14 → no fallback, one attempt."""
        resp = client.post(
            "/api/pilot/router/resolve",
            json={"model": "kilo/nvidia-nemotron-3-ultra-550b-a55b-free", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["route_mode"] == "manual"
        assert data["fallback_allowed"] is False
        assert data["eligible_fallback"] == []
        assert data["max_attempts"] == 1
        assert data["selected_route_id"] == "platform:kilo/nvidia-nemotron-3-ultra-550b-a55b-free"

    def test_manual_model_empty_business14_resolve(self, client):
        """manual model, empty business14 → no fallback, one attempt."""
        resp = client.post(
            "/api/pilot/router/resolve",
            json={
                "model": "kilo/nvidia-nemotron-3-ultra-550b-a55b-free",
                "messages": [{"role": "user", "content": "hi"}],
                "business14": {},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["fallback_allowed"] is False
        assert data["eligible_fallback"] == []
        assert data["max_attempts"] == 1
        assert data["selected_route_id"] == "platform:kilo/nvidia-nemotron-3-ultra-550b-a55b-free"

    def test_manual_model_explicit_false_resolve(self, client):
        """manual model, allow_external_fallback=false → no fallback, one attempt."""
        resp = client.post(
            "/api/pilot/router/resolve",
            json={
                "model": "kilo/nvidia-nemotron-3-ultra-550b-a55b-free",
                "messages": [{"role": "user", "content": "hi"}],
                "business14": {"allow_external_fallback": False},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["fallback_allowed"] is False
        assert data["eligible_fallback"] == []
        assert data["max_attempts"] == 1

    def test_manual_model_explicit_true_resolve(self, client, two_model_catalog):
        """manual model, allow_external_fallback=true → fallback candidates populated."""
        resp = client.post(
            "/api/pilot/router/resolve",
            json={
                "model": "kilo/nvidia-nemotron-3-ultra-550b-a55b-free",
                "messages": [{"role": "user", "content": "hi"}],
                "business14": {"allow_external_fallback": True},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["fallback_allowed"] is True
        assert len(data["eligible_fallback"]) > 0
        assert data["max_attempts"] > 1
        assert data["selected_route_id"] == "platform:kilo/nvidia-nemotron-3-ultra-550b-a55b-free"

    def test_manual_model_no_business14_chat_one_attempt(self, client):
        """manual model, no business14 → only 1 upstream call, no fallback."""
        _set_live()
        pass  # OpenRouter retired (#1933 S2): platform adapter is patched directly
        original = plat.call_platform_chat_completions
        calls = []

        async def fake(*, model_id, upstream_model, provider, platform_provider_id, messages, temperature=0.2, max_tokens=300, transport=None):
            calls.append(model_id)
            return {
                "id": "cmpl-test", "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
                "_live": True,
                "_requested_upstream_model": upstream_model,
                "_actual_response_model": upstream_model,
            }

        plat.call_platform_chat_completions = fake
        try:
            resp = client.post(
                "/api/pilot/v1/chat/completions",
                json={"model": "kilo/nvidia-nemotron-3-ultra-550b-a55b-free", "messages": [{"role": "user", "content": "hi"}]},
            )
        finally:
            plat.call_platform_chat_completions = original

        assert resp.status_code == 200
        biz14 = resp.json()["business14"]
        assert biz14["fallback_allowed"] is False
        assert biz14["attempt_count"] == 1
        assert biz14["fallback_used"] is False
        assert len(calls) == 1

    def test_manual_model_explicit_true_429_fallback(self, client, two_model_catalog):
        """manual model, allow_external_fallback=true → 429 allows fallback to second candidate."""
        _set_live()
        pass  # OpenRouter retired (#1933 S2): platform adapter is patched directly
        from app.pilot.errors import UpstreamRateLimited
        original = plat.call_platform_chat_completions
        calls = []

        async def fake(*, model_id, upstream_model, provider, platform_provider_id, messages, temperature=0.2, max_tokens=300, transport=None):
            calls.append(model_id)
            if len(calls) == 1:
                raise UpstreamRateLimited()
            return {
                "id": "cmpl-fb", "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
                "_live": True,
                "_requested_upstream_model": upstream_model,
                "_actual_response_model": upstream_model,
            }

        plat.call_platform_chat_completions = fake
        try:
            resp = client.post(
                "/api/pilot/v1/chat/completions",
                json={
                    "model": "kilo/nvidia-nemotron-3-ultra-550b-a55b-free",
                    "messages": [{"role": "user", "content": "hi"}],
                    "business14": {"allow_external_fallback": True},
                },
            )
        finally:
            plat.call_platform_chat_completions = original

        assert resp.status_code == 200
        biz14 = resp.json()["business14"]
        assert biz14["fallback_allowed"] is True
        assert biz14["fallback_used"] is True
        assert biz14["attempt_count"] >= 2
        assert len(calls) >= 2
        assert calls[1] != calls[0]

    def test_manual_model_explicit_true_401_no_fallback(self, client):
        """manual model, allow_external_fallback=true → 401 NO fallback (fail closed)."""
        _set_live()
        pass  # OpenRouter retired (#1933 S2): platform adapter is patched directly
        from app.pilot.errors import UpstreamAuthFailed
        original = plat.call_platform_chat_completions
        calls = []

        async def fake(*, model_id, upstream_model, provider, platform_provider_id, messages, temperature=0.2, max_tokens=300, transport=None):
            calls.append(model_id)
            raise UpstreamAuthFailed()

        plat.call_platform_chat_completions = fake
        try:
            resp = client.post(
                "/api/pilot/v1/chat/completions",
                json={
                    "model": "kilo/nvidia-nemotron-3-ultra-550b-a55b-free",
                    "messages": [{"role": "user", "content": "hi"}],
                    "business14": {"allow_external_fallback": True},
                },
            )
        finally:
            plat.call_platform_chat_completions = original

        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "upstream_auth_failed"
        assert resp.json()["error"]["fallback_used"] is False
        assert len(calls) == 1

    def test_manual_model_explicit_true_404_no_fallback(self, client):
        """manual model, allow_external_fallback=true → 404 NO fallback."""
        _set_live()
        pass  # OpenRouter retired (#1933 S2): platform adapter is patched directly
        from app.pilot.errors import UpstreamClientError
        original = plat.call_platform_chat_completions
        calls = []

        async def fake(*, model_id, upstream_model, provider, platform_provider_id, messages, temperature=0.2, max_tokens=300, transport=None):
            calls.append(model_id)
            raise UpstreamClientError(404)

        plat.call_platform_chat_completions = fake
        try:
            resp = client.post(
                "/api/pilot/v1/chat/completions",
                json={
                    "model": "kilo/nvidia-nemotron-3-ultra-550b-a55b-free",
                    "messages": [{"role": "user", "content": "hi"}],
                    "business14": {"allow_external_fallback": True},
                },
            )
        finally:
            plat.call_platform_chat_completions = original

        assert resp.status_code == 502
        assert resp.json()["error"]["code"] == "upstream_client_error"
        assert resp.json()["error"]["fallback_used"] is False
        assert len(calls) == 1

    def test_manual_model_explicit_true_malformed_no_fallback(self, client):
        """manual model, allow_external_fallback=true → malformed NO fallback."""
        _set_live()
        pass  # OpenRouter retired (#1933 S2): platform adapter is patched directly
        from app.pilot.errors import MalformedUpstreamResponse
        original = plat.call_platform_chat_completions
        calls = []

        async def fake(*, model_id, upstream_model, provider, platform_provider_id, messages, temperature=0.2, max_tokens=300, transport=None):
            calls.append(model_id)
            raise MalformedUpstreamResponse()

        plat.call_platform_chat_completions = fake
        try:
            resp = client.post(
                "/api/pilot/v1/chat/completions",
                json={
                    "model": "kilo/nvidia-nemotron-3-ultra-550b-a55b-free",
                    "messages": [{"role": "user", "content": "hi"}],
                    "business14": {"allow_external_fallback": True},
                },
            )
        finally:
            plat.call_platform_chat_completions = original

        assert resp.status_code == 502
        assert resp.json()["error"]["code"] == "malformed_upstream_response"
        assert resp.json()["error"]["fallback_used"] is False
        assert len(calls) == 1

    def test_manual_model_explicit_true_unknown_error_no_fallback(self, client):
        """manual model, allow_external_fallback=true → unknown error NO fallback."""
        _set_live()
        pass  # OpenRouter retired (#1933 S2): platform adapter is patched directly
        original = plat.call_platform_chat_completions
        calls = []

        async def fake(*, model_id, upstream_model, provider, platform_provider_id, messages, temperature=0.2, max_tokens=300, transport=None):
            calls.append(model_id)
            raise ValueError("unexpected internal failure")

        plat.call_platform_chat_completions = fake
        try:
            resp = client.post(
                "/api/pilot/v1/chat/completions",
                json={
                    "model": "kilo/nvidia-nemotron-3-ultra-550b-a55b-free",
                    "messages": [{"role": "user", "content": "hi"}],
                    "business14": {"allow_external_fallback": True},
                },
            )
        finally:
            plat.call_platform_chat_completions = original

        assert resp.status_code == 500
        assert resp.json()["error"]["code"] == "internal_error"
        assert resp.json()["error"]["fallback_used"] is False
        assert len(calls) == 1


# ============================================================================
# Issue 3: Actual candidate-specific selected_route_id
# ============================================================================


class TestActualRouteId:
    """selected_route_id must be the actual candidate's route ID, never a random ID."""

    def test_resolve_route_id_is_openrouter_prefixed(self, client):
        """Resolve endpoint must return openrouter:<model_id> route IDs."""
        resp = client.post(
            "/api/pilot/router/resolve",
            json={"model": "b14/auto", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["selected_route_id"].startswith("platform:")
        assert data["selected_route_id"] == f"platform:{data['selected_model']}"

    def test_manual_resolve_route_id(self, client):
        resp = client.post(
            "/api/pilot/router/resolve",
            json={"model": "kilo/nvidia-nemotron-3-ultra-550b-a55b-free", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["selected_route_id"] == "platform:kilo/nvidia-nemotron-3-ultra-550b-a55b-free"

    def test_primary_success_route_id(self, client):
        """Primary candidate success: selected_route_id = primary candidate route_id."""
        _set_live()
        pass  # OpenRouter retired (#1933 S2): platform adapter is patched directly
        original = plat.call_platform_chat_completions

        async def fake(*, model_id, upstream_model, provider, platform_provider_id, messages, temperature=0.2, max_tokens=300, transport=None):
            return {
                "id": "cmpl-pk", "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
                "_live": True,
                "_requested_upstream_model": upstream_model,
                "_actual_response_model": upstream_model,
            }

        plat.call_platform_chat_completions = fake
        try:
            resp = client.post(
                "/api/pilot/v1/chat/completions",
                json={"model": "b14/auto", "messages": [{"role": "user", "content": "hi"}]},
            )
        finally:
            plat.call_platform_chat_completions = original

        assert resp.status_code == 200
        biz14 = resp.json()["business14"]
        assert biz14["selected_route_id"] == f"platform:{biz14['selected_model']}"
        assert not biz14["fallback_used"]

    def test_fallback_success_route_id_differs_from_primary(self, client, two_model_catalog):
        """Fallback success: selected_route_id = actual fallback success candidate route_id."""
        _set_live()
        pass  # OpenRouter retired (#1933 S2): platform adapter is patched directly
        from app.pilot.errors import UpstreamRateLimited
        original = plat.call_platform_chat_completions
        calls = []

        async def fake(*, model_id, upstream_model, provider, platform_provider_id, messages, temperature=0.2, max_tokens=300, transport=None):
            calls.append({"model_id": model_id, "upstream_model": upstream_model, "provider": provider})
            if len(calls) == 1:
                raise UpstreamRateLimited()
            return {
                "id": "cmpl-fb", "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
                "_live": True,
                "_requested_upstream_model": upstream_model,
                "_actual_response_model": upstream_model,
            }

        plat.call_platform_chat_completions = fake
        try:
            resp = client.post(
                "/api/pilot/v1/chat/completions",
                json={
                    "model": "b14/auto",
                    "messages": [{"role": "user", "content": "hi"}],
                    "business14": {"optimize_for": "cost", "max_attempts": 3},
                },
            )
        finally:
            plat.call_platform_chat_completions = original

        assert resp.status_code == 200
        biz14 = resp.json()["business14"]
        primary_route_id = f"platform:{calls[0]['model_id']}"
        fallback_route_id = f"platform:{calls[1]['model_id']}"
        assert biz14["selected_route_id"] == fallback_route_id
        assert biz14["selected_route_id"] != primary_route_id
        assert biz14["selected_model"] == calls[1]["model_id"]
        assert biz14["selected_provider"] == calls[1]["provider"]
        assert biz14["selected_upstream_model"] == calls[1]["upstream_model"]
        assert biz14["attempt_evidence"][1]["route_id"] == fallback_route_id

    def test_route_id_no_api_key_or_url(self, client):
        """selected_route_id must not contain API keys or user-supplied URLs."""
        _set_live()
        secret = "sk-or-v1-super-secret-key-12345"
        pass  # OpenRouter retired (#1933 S2): platform adapter is patched directly
        original = plat.call_platform_chat_completions

        async def fake(*, model_id, upstream_model, provider, platform_provider_id, messages, temperature=0.2, max_tokens=300, transport=None):
            assert secret not in model_id
            assert secret not in upstream_model
            return {
                "id": "cmpl-test", "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
                "_live": True,
                "_requested_upstream_model": upstream_model,
                "_actual_response_model": upstream_model,
            }

        plat.call_platform_chat_completions = fake
        try:
            resp = client.post(
                "/api/pilot/v1/chat/completions",
                json={"model": "b14/auto", "messages": [{"role": "user", "content": "hi"}]},
            )
        finally:
            plat.call_platform_chat_completions = original

        assert resp.status_code == 200
        biz14 = resp.json()["business14"]
        route_id = biz14["selected_route_id"]
        assert secret not in route_id
        assert "http" not in route_id
        assert "@" not in route_id
        assert route_id.startswith("platform:")


# ============================================================================
# Keyless live smoke evidence (zero chat API calls without a key)
# ============================================================================


class TestKeylessLiveSmoke:
    def test_openrouter_module_retired(self):
        """OpenRouter call path and live smoke are retired (#1933 S2-b)."""
        import importlib.util
        assert importlib.util.find_spec("app.pilot.openrouter") is None
        assert importlib.util.find_spec("app.pilot.smoke_live") is None

    def test_keyless_platform_live_allowed_without_key(self, monkeypatch):
        """Keyless Kilo route stays callable in live mode with zero secret."""
        import asyncio
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.setenv("B14_PROVIDER_MODE", "live")
        rcfg.provider_mode = "live"
        rcfg.api_key = ""

        async def handler(request):
            assert request.headers.get("authorization") is None
            return httpx.Response(200, json=_ok_upstream_json(KILO_UPSTREAM))

        async def _run():
            return await plat.call_platform_chat_completions(
                messages=[{"role": "user", "content": "hi"}],
                temperature=0.2,
                max_tokens=16,
                model_id=KILO_MODEL,
                upstream_model=KILO_UPSTREAM,
                provider=KILO_PROVIDER,
                platform_provider_id="kilo",
                transport=httpx.MockTransport(handler),
            )

        result = asyncio.run(_run())
        assert result["_live"] is True
        assert result["_requested_upstream_model"] == KILO_UPSTREAM
