"""Tests for Business 14 Alpha 1: OpenRouter Gateway + Router Core.

All tests are network-free (use httpx.MockTransport). No external network calls.
"""

from __future__ import annotations

import json

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.catalog import (
    CATALOG_MODELS,
    get_catalog_by_id,
    list_catalog_summaries,
    select_by_optimize,
    filter_catalog,
)
from app.pilot.openrouter_config import OpenRouterConfig, ALLOWED_OPENROUTER_HOSTS
from app.pilot.openrouter import call_openrouter_chat_completions, build_mock_metadata
from app.pilot import router_core as rcore
from app.pilot.router_core import (
    RouteDecision,
    resolve_manual_route,
    resolve_auto_route,
    resolve_route,
    is_error_fallback_allowed,
)
from app.pilot.errors import NoSafeRoute, PilotNotConfigured, UpstreamTimeout
from app.pilot.openrouter_config import openrouter_config as orcfg


@pytest.fixture()
def app():
    return create_app()


@pytest.fixture()
def client(app):
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_config():
    """Reset OpenRouter config + pilot settings between tests."""
    saved = {
        "api_key": orcfg.api_key,
        "provider_mode": orcfg.provider_mode,
        "base_url": orcfg.base_url,
        "site_url": orcfg.site_url,
        "site_name": orcfg.site_name,
    }
    from app.pilot.config import pilot_settings
    saved_pilot = {
        "pilot_base_url": pilot_settings.pilot_base_url,
        "pilot_model_id": pilot_settings.pilot_model_id,
        "provider_registry_json": pilot_settings.provider_registry_json,
        "pilot_provider_id": pilot_settings.pilot_provider_id,
        "pilot_upstream_model": pilot_settings.pilot_upstream_model,
    }
    orcfg.api_key = ""
    orcfg.provider_mode = "mock"
    orcfg.base_url = "https://openrouter.ai/api/v1"
    orcfg.site_url = ""
    orcfg.site_name = "Business 14 Korean AI Gateway"
    from app.pilot.registry import reset_registry
    reset_registry()
    yield
    orcfg.api_key = saved["api_key"]
    orcfg.provider_mode = saved["provider_mode"]
    orcfg.base_url = saved["base_url"]
    orcfg.site_url = saved["site_url"]
    orcfg.site_name = saved["site_name"]
    pilot_settings.pilot_base_url = saved_pilot["pilot_base_url"]
    pilot_settings.pilot_model_id = saved_pilot["pilot_model_id"]
    pilot_settings.provider_registry_json = saved_pilot["provider_registry_json"]
    pilot_settings.pilot_provider_id = saved_pilot["pilot_provider_id"]
    pilot_settings.pilot_upstream_model = saved_pilot["pilot_upstream_model"]
    reset_registry()


def _set_live(key: str = "sk-or-v1-real-key-1234567890abcdef") -> None:
    orcfg.api_key = key
    orcfg.provider_mode = "live"


# ============================================================================
# Host allow-list / URL validation
# ============================================================================

class TestHostAllowlist:
    def test_openrouter_host_allowed(self):
        cfg = OpenRouterConfig()
        cfg.validate_base_url("https://openrouter.ai/api/v1")

    def test_openrouter_host_trailing_dot_allowed(self):
        cfg = OpenRouterConfig()
        cfg.validate_base_url("https://openrouter.ai./api/v1")

    def test_allowlist_contains_openrouter(self):
        assert "openrouter.ai" in ALLOWED_OPENROUTER_HOSTS

    @pytest.mark.parametrize("bad_url", [
        "https://evil.com/api/v1",
        "https://openrouter.ai.evil.com/api/v1",
        "https://evil-openrouter.ai/api/v1",
        "https://notopenrouter.ai/api/v1",
        "https://openrouter.ai.attacker.com/api/v1",
        "http://openrouter.ai/api/v1",  # not https
        "https://localhost:8000/api/v1",
        "https://127.0.0.1/api/v1",
        "https://10.0.0.1/api/v1",
        "https://169.254.169.254/latest/meta-data/",
        "https://user:pass@openrouter.ai/api/v1",
    ])
    def test_arbitrary_urls_rejected(self, bad_url):
        cfg = OpenRouterConfig()
        with pytest.raises(ValueError):
            cfg.validate_base_url(bad_url)

    def test_query_param_key_forbidden(self):
        """Base URL must not include key as query parameter."""
        cfg = OpenRouterConfig()
        with pytest.raises(ValueError):
            cfg.validate_base_url("https://openrouter.ai/api/v1?key=sk-or-v1-abc")


# ============================================================================
# Key isolation / redaction
# ============================================================================

class TestKeyIsolation:
    def test_has_key_true_with_real_key(self):
        _set_live()
        assert orcfg.has_key is True

    def test_has_key_false_empty(self):
        orcfg.api_key = ""
        assert orcfg.has_key is False

    @pytest.mark.parametrize("bad_key", [
        "sk-your-key-here",
        "your-api-key",
        "test-key",
        "demo-key",
        "placeholder",
        "abc",  # too short
    ])
    def test_placeholder_key_not_valid(self, bad_key):
        orcfg.api_key = bad_key
        assert orcfg.has_key is False

    def test_key_not_in_redacted_summary(self):
        _set_live("sk-or-v1-very-secret-key-abcdef1234567890")
        summary = orcfg.redacted_summary()
        assert "sk-or-v1-very-secret-key" not in summary
        assert "abcdef1234567890" not in summary

    def test_safe_headers_no_query_param(self):
        _set_live()
        headers = orcfg.safe_headers()
        assert headers.get("Authorization", "").startswith("Bearer ")
        # Key must be in Authorization only, not in any URL
        assert "sk-or-v1" not in str(orcfg.base_url)

    def test_site_headers_are_not_secrets(self):
        _set_live()
        orcfg.site_url = "https://example.org"
        orcfg.site_name = "Business 14 Korean AI Gateway"
        headers = orcfg.safe_headers()
        assert headers.get("HTTP-Referer") == "https://example.org"
        assert headers.get("X-OpenRouter-Title") == "Business 14 Korean AI Gateway"
        assert "sk-or-v1" not in headers.get("HTTP-Referer", "")


class TestKeyRedaction:
    def test_mock_response_has_no_key(self):
        _set_live()
        resp = build_mock_metadata("b14req_test", "google/gemini-2.5-flash", "google/gemini-2.5-flash", "Google")
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
        d = resolve_manual_route("google/gemini-2.5-flash")
        assert d.route_mode == "manual"
        assert d.selected_model == "google/gemini-2.5-flash"
        assert d.selected_upstream_model == "google/gemini-2.5-flash"
        assert d.selected_provider == "Google"
        assert d.reason_codes == ["manual_selection"]
        assert d.credential_available is False  # mock mode

    def test_manual_route_unknown_model_no_safe_route(self):
        with pytest.raises(NoSafeRoute) as exc_info:
            resolve_manual_route("nonexistent/model")
        assert exc_info.value.reason_code == "model_not_in_catalog"
        assert exc_info.value.upstream_called is False

    def test_manual_route_no_upstream_call(self):
        d = resolve_manual_route("deepseek/deepseek-chat")
        assert d.evidence_status == "resolved_not_called"

    def test_manual_route_has_fallback_candidates(self):
        d = resolve_manual_route("google/gemini-2.5-flash")
        assert len(d.eligible_fallback) > 0


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
        # openrouter/free has zero cost — should be first for cost
        assert selected.input_price_usd_per_1m + selected.output_price_usd_per_1m <= 0.01

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
        assert data["selected_route_id"].startswith("b14route_")
        assert data["credential_available"] is False

    def test_resolve_manual_model(self, client):
        resp = client.post(
            "/api/pilot/router/resolve",
            json={
                "model": "google/gemini-2.5-flash",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["route_mode"] == "manual"
        assert data["selected_model"] == "google/gemini-2.5-flash"

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
    def test_429_fallback_uses_second_candidate(self, client):
        """Auto route: first candidate 429 → fallback to second."""
        calls = []

        def make_transport(status_seq):
            async def handler(request):
                import json as _json
                calls.append(_json.loads(request.read()))
                status = status_seq[min(len(calls) - 1, len(status_seq) - 1)]
                if status == 429:
                    return httpx.Response(429, json={"error": {"message": "rate limited"}})
                return httpx.Response(200, json={
                    "id": "cmpl-fb", "object": "chat.completion",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
                })
            return httpx.MockTransport(handler)

        # In live mode, first candidate fails 429, second succeeds
        _set_live()
        from app.pilot import openrouter as orv
        original = orv.call_openrouter_chat_completions
        seq = [429, 200]
        transport = make_transport(seq)
        orv.call_openrouter_chat_completions = make_async(seq)
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
            orv.call_openrouter_chat_completions = original

        assert resp.status_code == 200
        data = resp.json()
        assert data["business14"]["fallback_used"] is True
        assert data["business14"]["attempt_count"] >= 2


def make_async(status_seq):
    """Helper: monkeypatch call_openrouter_chat_completions to use MockTransport.

    Shared call counter persists across fallback attempts so the status
    sequence advances 429 → 200 as candidates are tried.
    """
    shared_calls = []

    async def _patched(messages, temperature, max_tokens, model_id, upstream_model, provider, transport=None):
        async def handler(request):
            import json as _json
            shared_calls.append(_json.loads(request.read()))
            idx = min(len(shared_calls) - 1, len(status_seq) - 1)
            status = status_seq[idx]
            if status == 429:
                return httpx.Response(429, json={"error": {"message": "rate limited"}})
            if status == 500:
                return httpx.Response(500, json={"error": {"message": "boom"}})
            return httpx.Response(200, json={
                "id": "cmpl-fb", "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
            })
        return await call_openrouter_chat_completions(
            messages=messages, temperature=temperature, max_tokens=max_tokens,
            model_id=model_id, upstream_model=upstream_model, provider=provider,
            transport=httpx.MockTransport(handler),
        )
    return _patched


class TestLiveFailClosed:
    def test_missing_key_live_fails_closed(self, client):
        """Live mode without key → error, no upstream call."""
        orcfg.provider_mode = "live"
        orcfg.api_key = ""
        resp = client.post(
            "/api/pilot/v1/chat/completions",
            json={"model": "b14/auto", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code in (401, 503)
        body = resp.text
        assert "sk-or-v1" not in body

    def test_placeholder_key_live_fails_closed(self, client):
        orcfg.provider_mode = "live"
        orcfg.api_key = "sk-your-key-here"
        resp = client.post(
            "/api/pilot/v1/chat/completions",
            json={"model": "b14/auto", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code in (401, 503)


# ============================================================================
# Mock mode
# ============================================================================

class TestMockMode:
    def test_mock_mode_returns_mock_response(self, client):
        resp = client.post(
            "/api/pilot/v1/chat/completions",
            json={"model": "google/gemini-2.5-flash", "messages": [{"role": "user", "content": "hi"}]},
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
        orcfg.provider_mode = "mock"  # but mode is mock
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
        _set_live()
        async def fake_upstream(request):
            assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
            auth = request.headers.get("authorization", "")
            assert auth.startswith("Bearer sk-or-v1-real-key-")
            assert request.headers.get("x-openrouter-title") == "Business 14 Korean AI Gateway"
            return httpx.Response(200, json={
                "id": "cmpl-live", "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "live OK"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            })
        result = await call_openrouter_chat_completions(
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.2,
            max_tokens=32,
            model_id="google/gemini-2.5-flash",
            upstream_model="google/gemini-2.5-flash",
            provider="Google",
            transport=httpx.MockTransport(fake_upstream),
        )
        assert result["_live"] is True
        assert result["usage"]["total_tokens"] == 30

    @pytest.mark.asyncio
    async def test_live_call_malformed_json(self):
        _set_live()
        from app.pilot.errors import MalformedUpstreamResponse
        async def fake_bad(request):
            return httpx.Response(200, text="not-json{{{")
        with pytest.raises(MalformedUpstreamResponse):
            await call_openrouter_chat_completions(
                messages=[{"role": "user", "content": "hi"}],
                temperature=0.2, max_tokens=32,
                model_id="google/gemini-2.5-flash",
                upstream_model="google/gemini-2.5-flash",
                provider="Google",
                transport=httpx.MockTransport(fake_bad),
            )

    @pytest.mark.asyncio
    async def test_live_call_401(self):
        _set_live()
        from app.pilot.errors import UpstreamAuthFailed
        async def fake_401(request):
            return httpx.Response(401, json={"error": {"message": "unauthorized"}})
        with pytest.raises(UpstreamAuthFailed):
            await call_openrouter_chat_completions(
                messages=[{"role": "user", "content": "hi"}],
                temperature=0.2, max_tokens=32,
                model_id="google/gemini-2.5-flash",
                upstream_model="google/gemini-2.5-flash",
                provider="Google",
                transport=httpx.MockTransport(fake_401),
            )

    @pytest.mark.asyncio
    async def test_live_call_timeout(self):
        _set_live()
        async def fake_timeout(request):
            raise httpx.TimeoutException("timed out")
        with pytest.raises(UpstreamTimeout):
            await call_openrouter_chat_completions(
                messages=[{"role": "user", "content": "hi"}],
                temperature=0.2, max_tokens=32,
                model_id="google/gemini-2.5-flash",
                upstream_model="google/gemini-2.5-flash",
                provider="Google",
                transport=httpx.MockTransport(fake_timeout),
            )

    @pytest.mark.asyncio
    async def test_live_call_429(self):
        _set_live()
        from app.pilot.errors import UpstreamRateLimited
        async def fake_429(request):
            return httpx.Response(429, json={"error": {"message": "slow down"}})
        with pytest.raises(UpstreamRateLimited):
            await call_openrouter_chat_completions(
                messages=[{"role": "user", "content": "hi"}],
                temperature=0.2, max_tokens=32,
                model_id="google/gemini-2.5-flash",
                upstream_model="google/gemini-2.5-flash",
                provider="Google",
                transport=httpx.MockTransport(fake_429),
            )

    @pytest.mark.asyncio
    async def test_live_call_500(self):
        _set_live()
        from app.pilot.errors import UpstreamServerError
        async def fake_500(request):
            return httpx.Response(500, json={"error": {"message": "oops"}})
        with pytest.raises(UpstreamServerError):
            await call_openrouter_chat_completions(
                messages=[{"role": "user", "content": "hi"}],
                temperature=0.2, max_tokens=32,
                model_id="google/gemini-2.5-flash",
                upstream_model="google/gemini-2.5-flash",
                provider="Google",
                transport=httpx.MockTransport(fake_500),
            )

    @pytest.mark.asyncio
    async def test_live_call_no_key(self):
        orcfg.provider_mode = "live"
        orcfg.api_key = ""
        with pytest.raises(PilotNotConfigured):
            await call_openrouter_chat_completions(
                messages=[{"role": "user", "content": "hi"}],
                temperature=0.2, max_tokens=32,
                model_id="google/gemini-2.5-flash",
                upstream_model="google/gemini-2.5-flash",
                provider="Google",
                transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
            )


# ============================================================================
# Cost estimates
# ============================================================================

class TestCostEstimate:
    def test_price_known_estimate(self):
        cm = get_catalog_by_id("google/gemini-2.5-flash")
        # 1M input @ $0.05, 1M output @ $0.10
        usd = cm.estimate_cost_usd(1_000_000, 1_000_000)
        assert usd is not None
        assert usd == pytest.approx(0.15, rel=1e-3)

    def test_price_unknown_null(self):
        cm = get_catalog_by_id("openrouter/free")
        # zero-price → estimate returns None
        usd = cm.estimate_cost_usd(1000, 500)
        assert usd is None
        krw = cm.estimate_cost_krw(1000, 500)
        assert krw is None

    def test_krw_uses_configured_rate(self):
        cm = get_catalog_by_id("google/gemini-2.5-flash")
        krw = cm.estimate_cost_krw(1_000_000, 1_000_000)
        assert krw is not None
        assert krw == pytest.approx(0.15 * 1380, rel=1e-3)

    def test_live_response_has_estimate(self):
        _set_live()
        from app.pilot.openrouter import build_live_metadata
        meta = build_live_metadata(
            request_id="b14req_test",
            model_id="google/gemini-2.5-flash",
            upstream_model="google/gemini-2.5-flash",
            provider="Google",
            latency_ms=100,
            prompt_tokens=1_000_000,
            completion_tokens=1_000_000,
            total_tokens=2_000_000,
        )
        assert meta["estimated_usd"] == pytest.approx(0.15, rel=1e-3)
        assert meta["estimated_krw"] == pytest.approx(0.15 * 1380, rel=1e-3)

    def test_unknown_price_estimate_null(self):
        _set_live()
        from app.pilot.openrouter import build_live_metadata
        meta = build_live_metadata(
            request_id="b14req_test",
            model_id="openrouter/free",
            upstream_model="google/gemini-2.0-flash",
            provider="OpenRouter (free)",
            latency_ms=100,
            prompt_tokens=1000,
            completion_tokens=500,
            total_tokens=1500,
        )
        assert meta["estimated_usd"] is None
        assert meta["estimated_krw"] is None


# ============================================================================
# API metadata completeness
# ============================================================================

class TestMetadataCompleteness:
    _REQUIRED_FIELDS = {
        "route_mode",
        "selected_provider",
        "selected_model",
        "selected_route_id",
        "reason_codes",
        "fallback_allowed",
        "fallback_used",
        "attempt_count",
        "route_evidence_status",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "estimated_usd",
        "estimated_krw",
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
        assert "google/gemini-2.5-flash" in ids

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
        assert "openrouter/free" in ids
        assert any("gemini" in i for i in ids)
        assert any("deepseek" in i or "qwen" in i or "mistral" in i for i in ids)
        assert any("claude" in i or "gpt" in i for i in ids)

    def test_all_catalog_models_enabled(self):
        assert all(m.enabled for m in CATALOG_MODELS)

    def test_catalog_by_id_lookup(self):
        assert get_catalog_by_id("google/gemini-2.5-flash") is not None
        assert get_catalog_by_id("nonexistent") is None

    def test_filter_by_capability(self):
        result = filter_catalog(required_capabilities=["chat"])
        assert len(result) == len(CATALOG_MODELS)

    def test_select_by_optimize_cost_first_free(self):
        sorted_models = select_by_optimize(CATALOG_MODELS, "cost", True)
        assert sorted_models[0].model_id == "openrouter/free"

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
        assert "google/gemini-2.5-flash" in resp.text

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
        from app.pilot import openrouter as orv
        original = orv.call_openrouter_chat_completions
        calls = []
        async def spy(*args, **kwargs):
            calls.append(kwargs.get("transport"))
            return await original(*args, **kwargs)
        orv.call_openrouter_chat_completions = spy
        try:
            resp = client.post(
                "/api/pilot/v1/chat/completions",
                json={"model": "b14/auto", "messages": [{"role": "user", "content": "hi"}]},
            )
        finally:
            orv.call_openrouter_chat_completions = original
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
            if os.path.basename(f) == this_file:
                continue  # self-references in this file's assertions are not network usage
            with open(f, encoding="utf-8") as fh:
                content = fh.read()
            # No real network clients used at runtime in tests
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
        assert orcfg.max_response_bytes == 1024 * 1024
        assert orcfg.max_error_body_chars == 500

    def test_timeout_bounds_configured(self):
        assert orcfg.connect_timeout_seconds <= 10
        assert orcfg.read_timeout_seconds <= 30
        assert orcfg.total_timeout_seconds <= 35


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
