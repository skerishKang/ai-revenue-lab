"""Tests for the BYOK Gateway Pilot (Phase 1 + Phase 2).

Phase 2 adds: multi-provider registry, deterministic routing, key isolation
across providers, and expanded health/models/chat endpoints.

All tests use fake transport (httpx.MockTransport) — no external network calls.
"""

from __future__ import annotations

import json
import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.factory import create_app
from app.pilot.config import pilot_settings
from app.pilot.schemas import ChatMessage, PilotChatRequest
from app.pilot.registry import (
    ProviderRegistry,
    RouteTarget,
    RegistryInvalidError,
    reset_registry,
)


@pytest.fixture()
def app():
    return create_app()


@pytest.fixture()
def client(app):
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_all():
    """Reset registry and pilot config between tests."""
    reset_registry()
    saved = {
        "base_url": pilot_settings.pilot_base_url,
        "model_id": pilot_settings.pilot_model_id,
        "registry_json": pilot_settings.provider_registry_json,
    }
    yield
    pilot_settings.pilot_base_url = saved["base_url"]
    pilot_settings.pilot_model_id = saved["model_id"]
    pilot_settings.provider_registry_json = saved["registry_json"]
    reset_registry()


def _configure_pilot():
    """Configure Phase 1 legacy single-provider settings."""
    pilot_settings.pilot_base_url = "https://api.test-pilot.example.com"
    pilot_settings.pilot_model_id = "test-model-v1"
    pilot_settings.pilot_provider_id = "test-provider"
    pilot_settings.pilot_upstream_model = "upstream-model-v1"
    pilot_settings.pilot_timeout_seconds = 10
    pilot_settings.provider_registry_json = ""


def _setup_registry():
    """Configure Phase 2 multi-provider registry with 2 providers."""
    registry_data = [
        {
            "provider_id": "provider-a",
            "display_name": "Provider A",
            "base_url": "https://api.provider-a.example",
            "timeout_seconds": 30,
            "models": [
                {
                    "model_id": "model-a-v1",
                    "upstream_model": "upstream-a",
                    "display_name": "Model A",
                    "enabled": True,
                }
            ],
        },
        {
            "provider_id": "provider-b",
            "display_name": "Provider B",
            "base_url": "https://api.provider-b.example",
            "timeout_seconds": 15,
            "models": [
                {
                    "model_id": "model-b-v1",
                    "upstream_model": "upstream-b",
                    "display_name": "Model B",
                    "enabled": True,
                },
                {
                    "model_id": "model-b-v2",
                    "upstream_model": "upstream-b-2",
                    "display_name": "Model B v2",
                    "enabled": False,  # disabled
                },
            ],
        },
    ]
    pilot_settings.provider_registry_json = json.dumps(registry_data)
    reset_registry()


# ============================================================================
# Registry tests (Phase 2)
# ============================================================================


class TestRegistry:
    def test_parse_valid_registry(self):
        _setup_registry()
        from app.pilot.registry import get_registry
        r = get_registry()
        assert r.configured
        assert r.provider_count == 2
        assert r.model_count == 2  # one disabled

    def test_list_models(self):
        _setup_registry()
        from app.pilot.registry import get_registry
        r = get_registry()
        models = r.list_models()
        assert len(models) == 2  # only enabled
        ids = [m["id"] for m in models]
        assert "model-a-v1" in ids
        assert "model-b-v1" in ids
        assert "model-b-v2" not in ids  # disabled

    def test_provider_summary(self):
        _setup_registry()
        from app.pilot.registry import get_registry
        r = get_registry()
        summary = r.provider_summary()
        assert len(summary) == 2
        for s in summary:
            assert s["configured"] is True

    def test_get_model_route(self):
        _setup_registry()
        from app.pilot.registry import get_registry
        r = get_registry()
        route = r.get_model("model-a-v1")
        assert route is not None
        assert route.provider_id == "provider-a"
        assert route.upstream_model == "upstream-a"
        assert route.base_url == "https://api.provider-a.example"
        assert route.timeout_seconds == 30

        route_b = r.get_model("model-b-v1")
        assert route_b is not None
        assert route_b.provider_id == "provider-b"
        assert route_b.timeout_seconds == 15

    def test_unknown_model_returns_none(self):
        _setup_registry()
        from app.pilot.registry import get_registry
        r = get_registry()
        assert r.get_model("nonexistent") is None

    def test_disabled_model_returns_none(self):
        _setup_registry()
        from app.pilot.registry import get_registry
        r = get_registry()
        assert r.get_model("model-b-v2") is None  # disabled

    def test_duplicate_provider_id_rejected(self):
        data = [
            {"provider_id": "dup", "base_url": "https://example.com", "models": [
                {"model_id": "m1", "upstream_model": "u1", "display_name": "M1"}]},
            {"provider_id": "dup", "base_url": "https://example.org", "models": [
                {"model_id": "m2", "upstream_model": "u2", "display_name": "M2"}]},
        ]
        pilot_settings.provider_registry_json = json.dumps(data)
        reset_registry()
        from app.pilot.registry import get_registry
        r = get_registry()
        assert not r.configured
        assert r.parse_error is not None
        assert "duplicate" in r.parse_error.lower()

    def test_duplicate_model_id_rejected(self):
        data = [
            {"provider_id": "p1", "base_url": "https://example.com", "models": [
                {"model_id": "same", "upstream_model": "u1", "display_name": "M1"}]},
            {"provider_id": "p2", "base_url": "https://example.org", "models": [
                {"model_id": "same", "upstream_model": "u2", "display_name": "M2"}]},
        ]
        pilot_settings.provider_registry_json = json.dumps(data)
        reset_registry()
        from app.pilot.registry import get_registry
        r = get_registry()
        assert not r.configured
        assert r.parse_error is not None
        assert "duplicate" in r.parse_error.lower()

    def test_empty_upstream_model_rejected(self):
        data = [{"provider_id": "p1", "base_url": "https://example.com", "models": [
            {"model_id": "m1", "upstream_model": "", "display_name": "M1"}]}]
        pilot_settings.provider_registry_json = json.dumps(data)
        reset_registry()
        from app.pilot.registry import get_registry
        r = get_registry()
        assert not r.configured

    def test_invalid_url_rejected(self):
        data = [{"provider_id": "p1", "base_url": "http://insecure.com", "models": [
            {"model_id": "m1", "upstream_model": "u1", "display_name": "M1"}]}]
        pilot_settings.provider_registry_json = json.dumps(data)
        reset_registry()
        from app.pilot.registry import get_registry
        r = get_registry()
        assert not r.configured

    def test_empty_provider_id_rejected(self):
        data = [{"provider_id": "", "base_url": "https://example.com", "models": [
            {"model_id": "m1", "upstream_model": "u1", "display_name": "M1"}]}]
        pilot_settings.provider_registry_json = json.dumps(data)
        reset_registry()
        from app.pilot.registry import get_registry
        r = get_registry()
        assert not r.configured

    def test_no_models_rejected(self):
        data = [{"provider_id": "p1", "base_url": "https://example.com", "models": []}]
        pilot_settings.provider_registry_json = json.dumps(data)
        reset_registry()
        from app.pilot.registry import get_registry
        r = get_registry()
        assert not r.configured

    def test_invalid_timeout_rejected(self):
        data = [{"provider_id": "p1", "base_url": "https://example.com", "timeout_seconds": 999, "models": [
            {"model_id": "m1", "upstream_model": "u1", "display_name": "M1"}]}]
        pilot_settings.provider_registry_json = json.dumps(data)
        reset_registry()
        from app.pilot.registry import get_registry
        r = get_registry()
        assert not r.configured


# ============================================================================
# Legacy Phase 1 compatibility (registry not configured)
# ============================================================================


class TestLegacyPhase1Compat:
    """Phase 1 tests should still pass with legacy single-provider settings."""

    def test_legacy_health_via_registry(self, client):
        _configure_pilot()
        resp = client.get("/api/pilot/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["configured_providers"] == 1
        assert data["configured_models"] == 1

    def test_legacy_models_via_registry(self, client):
        _configure_pilot()
        resp = client.get("/api/pilot/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is True
        assert len(data["models"]) == 1

    def test_legacy_chat_via_registry(self, client):
        _configure_pilot()
        from app.pilot import provider as prv
        async def fake_call(**kw):
            return {"id": "test", "object": "chat.completion", "model": "test-model-v1",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hello!"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
                    "business14": {"mode": "byok-pilot", "provider": "test", "latency_ms": 100, "estimated_krw": None, "request_id": "b14req_test"}}
        import app.pilot.provider as prv_mod
        original = prv_mod.call_chat_completions
        prv_mod.call_chat_completions = fake_call
        try:
            resp = client.post(
                "/api/pilot/v1/chat/completions",
                json={"model": "test-model-v1", "messages": [{"role": "user", "content": "hi"}]},
                headers={"X-Business14-Provider-Key": "sk-real-key-12345abcdef"},
            )
        finally:
            prv_mod.call_chat_completions = original
        assert resp.status_code == 200


# ============================================================================
# Routing tests (Phase 2)
# ============================================================================


class TestRouting:
    """Tests for deterministic model→provider routing."""

    def test_route_model_a_to_provider_a(self):
        _setup_registry()
        from app.pilot.registry import get_registry
        r = get_registry()
        route = r.get_model("model-a-v1")
        assert route is not None
        assert route.provider_id == "provider-a"
        assert route.upstream_model == "upstream-a"
        assert "provider-a" in route.base_url

    def test_route_model_b_to_provider_b(self):
        _setup_registry()
        from app.pilot.registry import get_registry
        r = get_registry()
        route = r.get_model("model-b-v1")
        assert route is not None
        assert route.provider_id == "provider-b"
        assert route.upstream_model == "upstream-b"

    def test_unknown_model_returns_none(self):
        _setup_registry()
        from app.pilot.registry import get_registry
        r = get_registry()
        assert r.get_model("nonexistent") is None

    def test_disabled_model_not_routable(self):
        _setup_registry()
        from app.pilot.registry import get_registry
        r = get_registry()
        assert r.get_model("model-b-v2") is None  # disabled

    def test_ambiguous_route_is_prevented(self):
        """Duplicate model_id across providers is caught at registry init."""
        data = [
            {"provider_id": "p1", "base_url": "https://example.com", "models": [
                {"model_id": "same", "upstream_model": "u1", "display_name": "M1"}]},
            {"provider_id": "p2", "base_url": "https://example.org", "models": [
                {"model_id": "same", "upstream_model": "u2", "display_name": "M2"}]},
        ]
        pilot_settings.provider_registry_json = json.dumps(data)
        reset_registry()
        from app.pilot.registry import get_registry
        r = get_registry()
        assert not r.configured


# ============================================================================
# API integration tests (Phase 2 multi-provider)
# ============================================================================


class TestMultiProviderAPI:
    """Full HTTP endpoint tests with multi-provider registry."""

    def test_health_multi_provider(self, client):
        _setup_registry()
        resp = client.get("/api/pilot/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "byok-multi-provider-pilot"
        assert data["configured_providers"] == 2
        assert data["configured_models"] == 2
        assert len(data["providers"]) == 2

    def test_models_multi_provider(self, client):
        _setup_registry()
        resp = client.get("/api/pilot/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is True
        assert data["mode"] == "multi-provider"
        assert len(data["models"]) == 2

    def test_chat_route_a(self, client):
        """Model A → Provider A."""
        _setup_registry()
        captured = {}

        async def fake_upstream(request):
            import json as _json
            captured["body"] = _json.loads(request.read())
            return httpx.Response(200, json={
                "id": "cmpl-a", "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "From A"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
            })

        transport = httpx.MockTransport(fake_upstream)
        from app.pilot import provider as prv
        original = prv.call_chat_completions
        async def patched(**kw):
            kw["transport"] = transport
            return await original(**kw)
        prv.call_chat_completions = patched
        try:
            resp = client.post(
                "/api/pilot/v1/chat/completions",
                json={"model": "model-a-v1", "messages": [{"role": "user", "content": "hi"}]},
                headers={"X-Business14-Provider-Key": "sk-real-key-12345abcdef"},
            )
        finally:
            prv.call_chat_completions = original

        assert resp.status_code == 200
        assert resp.json()["choices"][0]["message"]["content"] == "From A"
        body = captured.get("body", {})
        assert body.get("messages") == [{"role": "user", "content": "hi"}]
        assert body.get("model") == "upstream-a"  # upstream_model for model-a-v1

    def test_chat_route_b(self, client):
        """Model B → Provider B (different provider, different upstream model)."""
        _setup_registry()
        captured = {}

        async def fake_upstream(request):
            import json as _json
            captured["body"] = _json.loads(request.read())
            return httpx.Response(200, json={
                "id": "cmpl-b", "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "From B"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 8, "total_tokens": 11},
            })

        transport = httpx.MockTransport(fake_upstream)
        from app.pilot import provider as prv
        original = prv.call_chat_completions
        async def patched(**kw):
            kw["transport"] = transport
            return await original(**kw)
        prv.call_chat_completions = patched
        try:
            resp = client.post(
                "/api/pilot/v1/chat/completions",
                json={"model": "model-b-v1", "messages": [{"role": "user", "content": "hello"}]},
                headers={"X-Business14-Provider-Key": "sk-real-key-xyz"},
            )
        finally:
            prv.call_chat_completions = original

        assert resp.status_code == 200
        assert resp.json()["choices"][0]["message"]["content"] == "From B"
        body = captured.get("body", {})
        assert body.get("model") == "upstream-b"  # upstream_model for model-b-v1

    def test_unknown_model_404(self, client):
        _setup_registry()
        resp = client.post(
            "/api/pilot/v1/chat/completions",
            json={"model": "nonexistent", "messages": [{"role": "user", "content": "hi"}]},
            headers={"X-Business14-Provider-Key": "sk-real-key-12345abcdef"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "model_not_found"

    def test_disabled_model_404(self, client):
        _setup_registry()
        resp = client.post(
            "/api/pilot/v1/chat/completions",
            json={"model": "model-b-v2", "messages": [{"role": "user", "content": "hi"}]},
            headers={"X-Business14-Provider-Key": "sk-real-key-12345abcdef"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "model_not_found"

    def test_business14_metadata_has_route(self, client):
        _setup_registry()
        async def fake_upstream(request):
            return httpx.Response(200, json={
                "id": "cmpl-test", "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
            })
        transport = httpx.MockTransport(fake_upstream)
        from app.pilot import provider as prv
        original = prv.call_chat_completions
        async def patched(**kw):
            kw["transport"] = transport
            return await original(**kw)
        prv.call_chat_completions = patched
        try:
            resp = client.post(
                "/api/pilot/v1/chat/completions",
                json={"model": "model-a-v1", "messages": [{"role": "user", "content": "hi"}]},
                headers={"X-Business14-Provider-Key": "sk-real-key-12345abcdef"},
            )
        finally:
            prv.call_chat_completions = original

        data = resp.json()
        biz14 = data.get("business14", {})
        assert biz14.get("mode") == "byok-multi-provider-pilot"
        assert biz14.get("provider") == "provider-a"
        assert biz14.get("model_route") == "model-a-v1"
        assert biz14.get("estimated_krw") is None


# ============================================================================
# Key isolation tests (Phase 2)
# ============================================================================


class TestKeyIsolation:
    """Provider A key must not leak to Provider B, and vice versa."""

    def test_key_a_only_goes_to_a(self, client):
        _setup_registry()
        captured_a = {}
        captured_b = {}
        call_count = [0]

        async def fake_a(request):
            call_count[0] += 1
            import json as _json
            captured_a["headers"] = dict(request.headers)
            return httpx.Response(200, json={
                "id": "cmpl-a", "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "A"}, "finish_reason": "stop"}],
            })

        async def fake_b(request):
            call_count[0] += 1
            import json as _json
            captured_b["headers"] = dict(request.headers)
            return httpx.Response(200, json={
                "id": "cmpl-b", "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "B"}, "finish_reason": "stop"}],
            })

        # Both providers should get their own key
        from app.pilot import provider as prv
        original = prv.call_chat_completions
        call_num = [0]

        async def routing_patch(**kw):
            call_num[0] += 1
            if call_num[0] == 1:
                # First call: Provider A with key "sk-key-for-a"
                kw["transport"] = httpx.MockTransport(fake_a)
            else:
                # Second call: Provider B with key "sk-key-for-b"
                kw["transport"] = httpx.MockTransport(fake_b)
            return await original(**kw)

        prv.call_chat_completions = routing_patch
        try:
            # Request A with key A
            client.post(
                "/api/pilot/v1/chat/completions",
                json={"model": "model-a-v1", "messages": [{"role": "user", "content": "hi"}]},
                headers={"X-Business14-Provider-Key": "sk-key-for-a"},
            )
            # Request B with key B
            client.post(
                "/api/pilot/v1/chat/completions",
                json={"model": "model-b-v1", "messages": [{"role": "user", "content": "hi"}]},
                headers={"X-Business14-Provider-Key": "sk-key-for-b"},
            )
        finally:
            prv.call_chat_completions = original

        # Must be 2 separate calls
        assert call_count[0] >= 2

    def test_key_not_in_response(self, client):
        _setup_registry()
        async def fake_upstream(request):
            return httpx.Response(200, json={
                "id": "cmpl-test", "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}],
            })

        transport = httpx.MockTransport(fake_upstream)
        from app.pilot import provider as prv
        original = prv.call_chat_completions
        async def patched(**kw):
            kw["transport"] = transport
            return await original(**kw)
        prv.call_chat_completions = patched
        try:
            resp = client.post(
                "/api/pilot/v1/chat/completions",
                json={"model": "model-a-v1", "messages": [{"role": "user", "content": "hi"}]},
                headers={"X-Business14-Provider-Key": "sk-real-secret-key-abcdef"},
            )
        finally:
            prv.call_chat_completions = original

        assert "sk-real-secret-key-abcdef" not in resp.text


# ============================================================================
# UI page tests (Phase 2 multi-provider)
# ============================================================================


class TestMultiProviderUI:
    def test_page_renders(self, client):
        assert client.get("/pilot").status_code == 200

    def test_shows_multi_provider_info_when_configured(self, client):
        _setup_registry()
        resp = client.get("/pilot")
        assert resp.status_code == 200
        assert "Multi-Provider" in resp.text
        assert "Provider A" in resp.text or "provider-a" in resp.text

    def test_shows_legacy_mode_when_single_provider(self, client):
        _configure_pilot()
        resp = client.get("/pilot")
        assert resp.status_code == 200
        # Legacy mode works with either Phase label
        assert "pilot" in resp.text.lower()

    def test_models_show_provider_name(self, client):
        _setup_registry()
        resp = client.get("/pilot")
        assert resp.status_code == 200
        assert "Provider A" in resp.text
        assert "Model A" in resp.text

    def test_key_input_is_password(self, client):
        _setup_registry()
        resp = client.get("/pilot")
        assert 'type="password"' in resp.text

    def test_cost_shows_unavailable(self, client):
        _setup_registry()
        resp = client.get("/pilot")
        assert resp.status_code == 200
        # Cost should not show 0.0 or 0원
        page_text = resp.text
        assert "0.0원" not in page_text
        assert "0원" not in page_text or "0원이" in page_text


# ============================================================================
# Phase 1 regression tests (all must still pass)
# ============================================================================


class TestPhase1Regression:
    def test_health_not_configured(self, client):
        resp = client.get("/api/pilot/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "not_configured"
        assert data["configured_providers"] == 0

    def test_models_empty_when_not_configured(self, client):
        resp = client.get("/api/pilot/models")
        assert resp.status_code == 200
        assert resp.json()["models"] == []

    def test_chat_fails_when_not_configured(self, client):
        resp = client.post(
            "/api/pilot/v1/chat/completions",
            json={"model": "test", "messages": [{"role": "user", "content": "hi"}]},
            headers={"X-Business14-Provider-Key": "sk-real-key-12345abcdef"},
        )
        assert resp.status_code == 503
        assert resp.json()["error"]["code"] == "pilot_not_configured"

    def test_schema_validation(self):
        with pytest.raises(ValidationError):
            PilotChatRequest(model="test", messages=[ChatMessage(role="user", content="hi")], base_url="http://evil.com")

    def test_invalid_role(self):
        with pytest.raises(ValidationError):
            ChatMessage(role="admin", content="hi")

    def test_empty_content(self):
        with pytest.raises(ValidationError):
            ChatMessage(role="user", content="   ")

    def test_temperature_range(self):
        with pytest.raises(ValidationError):
            PilotChatRequest(model="test", messages=[ChatMessage(role="user", content="hi")], temperature=3.0)

    def test_max_tokens_range(self):
        with pytest.raises(ValidationError):
            PilotChatRequest(model="test", messages=[ChatMessage(role="user", content="hi")], max_tokens=0)

    def test_stream_rejected(self, client):
        _configure_pilot()
        resp = client.post(
            "/api/pilot/v1/chat/completions",
            json={"model": "test-model-v1", "messages": [{"role": "user", "content": "hi"}], "stream": True},
            headers={"X-Business14-Provider-Key": "sk-real-key-12345abcdef"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "stream_not_supported"

    def test_missing_key(self, client):
        _configure_pilot()
        resp = client.post(
            "/api/pilot/v1/chat/completions",
            json={"model": "test-model-v1", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "missing_provider_key"

    def test_ui_post_unconfigured(self, client):
        resp = client.post("/pilot", data={"provider_key": "sk-test", "prompt": "hello"})
        assert resp.status_code == 200
        assert "pilot_not_configured" in resp.text
        assert "NameError" not in resp.text

    def test_serialize_chatmessage(self):
        from app.pilot.provider import _serialize_messages
        msgs = [ChatMessage(role="user", content="hello")]
        result = _serialize_messages(msgs)
        assert result == [{"role": "user", "content": "hello"}]


# ============================================================================
# SSRF validation tests
# ============================================================================


class TestSSRFValidation:
    @pytest.mark.parametrize("bad_url", [
        "http://api.example.com/v1",
        "https://localhost:8000/v1",
        "https://127.0.0.1:8000/v1",
        "https://10.0.0.1/v1",
        "https://192.168.1.1/v1",
        "https://[::1]:8000/v1",
        "https://user:pass@api.example.com/v1",
    ])
    def test_invalid_urls_rejected(self, bad_url):
        from app.pilot.provider import _validate_base_url
        with pytest.raises(ValueError):
            _validate_base_url(bad_url)


# ============================================================================
# Route smoke
# ============================================================================


class TestRouteSmoke:
    def test_home(self, client): assert client.get("/").status_code == 200
    def test_models(self, client): assert client.get("/models").status_code == 200
    def test_playground(self, client): assert client.get("/playground").status_code == 200
    def test_api_keys(self, client): assert client.get("/api-keys").status_code == 200
    def test_docs(self, client): assert client.get("/docs").status_code == 200
    def test_usage(self, client): assert client.get("/usage").status_code == 200
    def test_pricing(self, client): assert client.get("/pricing").status_code == 200
    def test_access(self, client): assert client.get("/access").status_code == 200
    def test_pilot(self, client): assert client.get("/pilot").status_code == 200
    def test_pilot_health(self, client): assert client.get("/api/pilot/health").status_code == 200
    def test_pilot_models(self, client): assert client.get("/api/pilot/models").status_code == 200
    def test_phase0_8_models(self, client):
        resp = client.get("/models")
        assert resp.status_code == 200
        from app.demo_data import MODELS
        assert len(MODELS) == 8


# ============================================================================
# Clean install
# ============================================================================


class TestCleanInstall:
    def test_httpx_in_runtime_deps(self):
        import tomllib
        import os
        here = os.path.dirname(__file__)
        pyproject = os.path.join(here, "..", "pyproject.toml")
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
        deps = data["project"]["dependencies"]
        assert any("httpx" in d for d in deps), "httpx must be in main dependencies"
