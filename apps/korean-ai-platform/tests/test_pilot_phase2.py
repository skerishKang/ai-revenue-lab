"""Tests for Phase 2: Multi-Provider BYOK Model Routing Pilot.

All tests use fake transport (httpx.MockTransport) — no external network calls.
"""

from __future__ import annotations

import json

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.config import pilot_settings
from app.pilot.routing import RouteTarget
from app.pilot.registry import (
    ProviderRegistry,
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


def _setup_invalid_registry():
    """Set an invalid registry JSON (syntactically valid but structurally wrong)."""
    pilot_settings.provider_registry_json = "[]"
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

    def test_all_models_disabled_rejected(self):
        data = [{"provider_id": "p1", "base_url": "https://example.com", "models": [
            {"model_id": "m1", "upstream_model": "u1", "display_name": "M1", "enabled": False},
            {"model_id": "m2", "upstream_model": "u2", "display_name": "M2", "enabled": False},
        ]}]
        pilot_settings.provider_registry_json = json.dumps(data)
        reset_registry()
        from app.pilot.registry import get_registry
        r = get_registry()
        assert not r.configured
        assert r.parse_error is not None
        assert "enabled" in r.parse_error.lower()

    def test_enabled_non_bool_rejected(self):
        data = [{"provider_id": "p1", "base_url": "https://example.com", "models": [
            {"model_id": "m1", "upstream_model": "u1", "display_name": "M1", "enabled": "yes"}]}]
        pilot_settings.provider_registry_json = json.dumps(data)
        reset_registry()
        from app.pilot.registry import get_registry
        r = get_registry()
        assert not r.configured
        assert r.parse_error is not None
        assert "boolean" in r.parse_error.lower()

    def test_disabled_model_tracked(self):
        _setup_registry()
        from app.pilot.registry import get_registry
        r = get_registry()
        assert r.disabled_model_count == 1
        assert r.is_model_disabled("model-b-v2")
        assert not r.is_model_disabled("model-a-v1")


# ============================================================================
# Configuration resolver tests
# ============================================================================


class TestConfigurationResolver:
    def test_valid_registry_state(self):
        _setup_registry()
        from app.pilot.routing import resolve_configuration, PilotConfigurationState
        assert resolve_configuration() == PilotConfigurationState.VALID_REGISTRY

    def test_invalid_registry_state(self):
        _setup_invalid_registry()
        from app.pilot.routing import resolve_configuration, PilotConfigurationState
        assert resolve_configuration() == PilotConfigurationState.INVALID_REGISTRY

    def test_invalid_registry_with_legacy_fail_closed(self):
        """Legacy config must NOT be used when registry is invalid."""
        _setup_invalid_registry()
        pilot_settings.pilot_base_url = "https://legacy.example.com"
        pilot_settings.pilot_model_id = "legacy-model"
        from app.pilot.routing import resolve_configuration, PilotConfigurationState
        assert resolve_configuration() == PilotConfigurationState.INVALID_REGISTRY

    def test_legacy_state(self):
        from app.pilot.config import pilot_settings
        pilot_settings.pilot_base_url = "https://api.example.com"
        pilot_settings.pilot_model_id = "test-model"
        from app.pilot.routing import resolve_configuration, PilotConfigurationState
        assert resolve_configuration() == PilotConfigurationState.LEGACY

    def test_not_configured_state(self):
        from app.pilot.routing import resolve_configuration, PilotConfigurationState
        assert resolve_configuration() == PilotConfigurationState.NOT_CONFIGURED


# ============================================================================
# Routing tests (Phase 2)
# ============================================================================


class TestRouting:
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
    def test_health_multi_provider(self, client):
        _setup_registry()
        resp = client.get("/api/pilot/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "byok-multi-provider-pilot"
        assert data["configured_providers"] == 2
        assert data["configured_models"] == 2
        assert len(data["providers"]) == 2

    def test_health_invalid_registry(self, client):
        _setup_invalid_registry()
        resp = client.get("/api/pilot/health")
        assert resp.status_code == 500
        data = resp.json()
        assert data["error"]["code"] == "registry_invalid"
        assert data["error"]["message"] == "Provider registry 설정이 올바르지 않습니다."
        assert data["error"]["request_id"].startswith("b14req_")

    def test_health_invalid_registry_with_legacy(self, client):
        _setup_invalid_registry()
        pilot_settings.pilot_base_url = "https://legacy.example.com"
        pilot_settings.pilot_model_id = "legacy-model"
        resp = client.get("/api/pilot/health")
        assert resp.status_code == 500
        data = resp.json()
        assert data["error"]["code"] == "registry_invalid"
        # Legacy provider info must NOT appear in response
        assert "legacy" not in str(data)

    def test_models_multi_provider(self, client):
        _setup_registry()
        resp = client.get("/api/pilot/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is True
        assert data["mode"] == "multi-provider"
        assert len(data["models"]) == 2

    def test_models_invalid_registry(self, client):
        _setup_invalid_registry()
        resp = client.get("/api/pilot/models")
        assert resp.status_code == 500
        data = resp.json()
        assert data["error"]["code"] == "registry_invalid"

    def test_chat_invalid_registry(self, client):
        _setup_invalid_registry()
        resp = client.post(
            "/api/pilot/v1/chat/completions",
            json={"model": "test", "messages": [{"role": "user", "content": "hi"}]},
            headers={"X-Business14-Provider-Key": "sk-real-key-12345abcdef"},
        )
        assert resp.status_code == 500
        assert resp.json()["error"]["code"] == "registry_invalid"
        assert resp.json()["error"].get("request_id", "").startswith("b14req_")

    def test_chat_invalid_registry_with_legacy(self, client):
        _setup_invalid_registry()
        pilot_settings.pilot_base_url = "https://legacy.example.com"
        pilot_settings.pilot_model_id = "legacy-model"
        resp = client.post(
            "/api/pilot/v1/chat/completions",
            json={"model": "test", "messages": [{"role": "user", "content": "hi"}]},
            headers={"X-Business14-Provider-Key": "sk-real-key-12345abcdef"},
        )
        assert resp.status_code == 500
        assert resp.json()["error"]["code"] == "registry_invalid"

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
        data = resp.json()
        assert data["choices"][0]["message"]["content"] == "From A"
        assert data["model"] == "model-a-v1"  # response model = model-a-v1 (Phase 2)
        body = captured.get("body", {})
        assert body.get("messages") == [{"role": "user", "content": "hi"}]
        assert body.get("model") == "upstream-a"  # upstream_model for model-a-v1

    def test_chat_route_b(self, client):
        """Model B → Provider B."""
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
        data = resp.json()
        assert data["choices"][0]["message"]["content"] == "From B"
        assert data["model"] == "model-b-v1"  # response model = model-b-v1
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

    def test_disabled_model_returns_model_disabled(self, client):
        _setup_registry()
        resp = client.post(
            "/api/pilot/v1/chat/completions",
            json={"model": "model-b-v2", "messages": [{"role": "user", "content": "hi"}]},
            headers={"X-Business14-Provider-Key": "sk-real-key-12345abcdef"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "model_disabled"

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
        assert biz14.get("request_id", "").startswith("b14req_")


# ============================================================================
# Key isolation tests (Phase 2)
# ============================================================================


class TestKeyIsolation:
    def test_key_a_only_goes_to_a(self, client):
        _setup_registry()
        captured_a = {}
        captured_b = {}
        call_count = [0]

        async def fake_a(request):
            call_count[0] += 1
            import json as _json
            captured_a["headers"] = dict(request.headers)
            captured_a["url"] = str(request.url)
            return httpx.Response(200, json={
                "id": "cmpl-a", "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "A"}, "finish_reason": "stop"}],
            })

        async def fake_b(request):
            call_count[0] += 1
            import json as _json
            captured_b["headers"] = dict(request.headers)
            captured_b["url"] = str(request.url)
            return httpx.Response(200, json={
                "id": "cmpl-b", "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "B"}, "finish_reason": "stop"}],
            })

        from app.pilot import provider as prv
        original = prv.call_chat_completions
        call_num = [0]

        async def routing_patch(**kw):
            call_num[0] += 1
            if call_num[0] == 1:
                kw["transport"] = httpx.MockTransport(fake_a)
            else:
                kw["transport"] = httpx.MockTransport(fake_b)
            return await original(**kw)

        prv.call_chat_completions = routing_patch
        try:
            client.post(
                "/api/pilot/v1/chat/completions",
                json={"model": "model-a-v1", "messages": [{"role": "user", "content": "hi"}]},
                headers={"X-Business14-Provider-Key": "sk-key-for-a"},
            )
            client.post(
                "/api/pilot/v1/chat/completions",
                json={"model": "model-b-v1", "messages": [{"role": "user", "content": "hi"}]},
                headers={"X-Business14-Provider-Key": "sk-key-for-b"},
            )
        finally:
            prv.call_chat_completions = original

        assert call_count[0] >= 2

        # Verify Provider A received only key A
        auth_a = captured_a.get("headers", {}).get("authorization", "")
        assert "sk-key-for-a" in auth_a, "Provider A must receive its own key"
        assert "sk-key-for-b" not in auth_a, "Provider A must NOT receive Provider B key"

        # Verify Provider B received only key B
        auth_b = captured_b.get("headers", {}).get("authorization", "")
        assert "sk-key-for-b" in auth_b, "Provider B must receive its own key"
        assert "sk-key-for-a" not in auth_b, "Provider B must NOT receive Provider A key"

        # Verify URL host matches expected provider
        url_a = captured_a.get("url", "")
        url_b = captured_b.get("url", "")
        assert "provider-a" in url_a, f"Provider A call must go to provider-a URL, got: {url_a}"
        assert "provider-b" in url_b, f"Provider B call must go to provider-b URL, got: {url_b}"

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

    def test_invalid_registry_ui(self, client):
        _setup_invalid_registry()
        resp = client.get("/pilot")
        assert resp.status_code == 200
        assert "registry_invalid" in resp.text or "올바르지 않습니다" in resp.text

    def test_invalid_registry_with_legacy_ui(self, client):
        _setup_invalid_registry()
        pilot_settings.pilot_base_url = "https://legacy.example.com"
        pilot_settings.pilot_model_id = "legacy-model"
        resp = client.get("/pilot")
        assert resp.status_code == 200
        assert "registry_invalid" in resp.text or "올바르지 않습니다" in resp.text

    def test_invalid_registry_post(self, client):
        _setup_invalid_registry()
        resp = client.post("/pilot", data={"provider_key": "sk-test", "prompt": "hello"})
        assert resp.status_code == 200
        assert "registry_invalid" in resp.text or "올바르지 않습니다" in resp.text
        assert "NameError" not in resp.text

    def test_shows_legacy_mode_when_single_provider(self, client):
        pilot_settings.pilot_base_url = "https://api.example.com"
        pilot_settings.pilot_model_id = "test-model-v1"
        pilot_settings.pilot_provider_id = "test-provider"
        pilot_settings.pilot_upstream_model = "upstream-v1"
        pilot_settings.pilot_timeout_seconds = 10
        resp = client.get("/pilot")
        assert resp.status_code == 200
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
        page_text = resp.text
        assert "0.0원" not in page_text
        assert "0원" not in page_text or "0원이" in page_text


# ============================================================================
# Phase 1 legacy compatibility tests (via registry)
# ============================================================================


class TestLegacyPhase1Compat:
    def test_legacy_health_via_registry(self, client):
        pilot_settings.pilot_base_url = "https://api.test-pilot.example.com"
        pilot_settings.pilot_model_id = "test-model-v1"
        pilot_settings.pilot_provider_id = "test-provider"
        pilot_settings.pilot_upstream_model = "upstream-model-v1"
        pilot_settings.pilot_timeout_seconds = 10
        pilot_settings.provider_registry_json = ""
        reset_registry()

        resp = client.get("/api/pilot/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["configured_providers"] == 1

    def test_legacy_models_via_registry(self, client):
        pilot_settings.pilot_base_url = "https://api.test-pilot.example.com"
        pilot_settings.pilot_model_id = "test-model-v1"
        pilot_settings.pilot_provider_id = "test-provider"
        pilot_settings.pilot_upstream_model = "upstream-model-v1"
        pilot_settings.pilot_timeout_seconds = 10
        pilot_settings.provider_registry_json = ""
        reset_registry()

        resp = client.get("/api/pilot/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is True
        assert len(data["models"]) == 1

    def test_legacy_chat_via_registry(self, client):
        pilot_settings.pilot_base_url = "https://api.test-pilot.example.com"
        pilot_settings.pilot_model_id = "test-model-v1"
        pilot_settings.pilot_provider_id = "test-provider"
        pilot_settings.pilot_upstream_model = "upstream-model-v1"
        pilot_settings.pilot_timeout_seconds = 10
        pilot_settings.provider_registry_json = ""
        reset_registry()

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
# Sentinel-based non-exposure tests (CTO spec: internal details must not leak)
# ============================================================================


class TestRegistrySentinelNonExposure:
    """Test that internal registry parse_error details are never exposed to users.

    Uses sentinel strings (secret-provider-duplicate, secret-model-duplicate,
    internal-registry-secret.example) that would appear in responses if
    parse_error content leaks through any endpoint or UI path.
    """

    _SENTINELS = [
        "secret-provider-duplicate",
        "secret-model-duplicate",
        "internal-registry-secret.example",
        "http://internal-registry-secret.example/private",
        "Duplicate provider_id",
        "Duplicate model_id",
        "must use https",
        "parse_error",
    ]

    @pytest.fixture(params=[
        # (registry_json, legacy_on) — each case is a structurally invalid registry
        (json.dumps([{"provider_id": "secret-provider-duplicate", "base_url": "https://api.example.com", "models": [{"model_id": "m1", "upstream_model": "u1", "display_name": "M1"}]},
                     {"provider_id": "secret-provider-duplicate", "base_url": "https://api.example.org", "models": [{"model_id": "m2", "upstream_model": "u2", "display_name": "M2"}]}]), False),
        (json.dumps([{"provider_id": "p1", "base_url": "http://internal-registry-secret.example/private", "models": [{"model_id": "m1", "upstream_model": "u1", "display_name": "M1"}]}]), False),
        (json.dumps([{"provider_id": "p1", "base_url": "https://api.example.com", "models": [{"model_id": "secret-model-duplicate", "upstream_model": "u1", "display_name": "M1"}]},
                     {"provider_id": "p2", "base_url": "https://api.example.org", "models": [{"model_id": "secret-model-duplicate", "upstream_model": "u2", "display_name": "M2"}]}]), False),
        (json.dumps([{"provider_id": "p1", "base_url": "https://api.example.com", "models": [{"model_id": "m1", "upstream_model": "u1", "display_name": "M1", "enabled": False}]}]), False),
        (json.dumps([]), False),
        # With legacy config also set (must still fail closed, no legacy info leaked)
        (json.dumps([{"provider_id": "secret-provider-duplicate", "base_url": "https://api.example.com", "models": [{"model_id": "m1", "upstream_model": "u1", "display_name": "M1"}]},
                     {"provider_id": "secret-provider-duplicate", "base_url": "https://api.example.org", "models": [{"model_id": "m2", "upstream_model": "u2", "display_name": "M2"}]}]), True),
    ])
    def _invalid_registry_setup(self, request):
        yield request.param

    @pytest.fixture
    def _apply_invalid_registry(self, client, _invalid_registry_setup):
        registry_json, legacy_on = _invalid_registry_setup
        pilot_settings.provider_registry_json = registry_json
        if legacy_on:
            pilot_settings.pilot_base_url = "https://legacy.example.com"
            pilot_settings.pilot_model_id = "legacy-model"
            pilot_settings.pilot_provider_id = "legacy-provider"
            pilot_settings.pilot_upstream_model = "upstream-legacy"
        else:
            pilot_settings.pilot_base_url = ""
            pilot_settings.pilot_model_id = ""
        reset_registry()
        return client

    def _assert_no_leakage(self, resp_text: str, endpoint_name: str):
        for sentinel in self._SENTINELS:
            assert sentinel not in resp_text, (
                f"Sentinel '{sentinel}' leaked in {endpoint_name} response"
            )

    def _assert_invalid_registry_error(self, resp, endpoint_name: str):
        assert resp.status_code == 500, f"{endpoint_name}: expected 500, got {resp.status_code}"
        data = resp.json()
        assert data["error"]["code"] == "registry_invalid"
        assert data["error"]["message"] == "Provider registry 설정이 올바르지 않습니다."
        assert data["error"]["request_id"].startswith("b14req_")
        self._assert_no_leakage(resp.text, endpoint_name)

    def test_health_no_leakage(self, _apply_invalid_registry):
        resp = _apply_invalid_registry.get("/api/pilot/health")
        self._assert_invalid_registry_error(resp, "health")

    def test_models_no_leakage(self, _apply_invalid_registry):
        resp = _apply_invalid_registry.get("/api/pilot/models")
        self._assert_invalid_registry_error(resp, "models")

    def test_chat_no_leakage(self, _apply_invalid_registry):
        resp = _apply_invalid_registry.post(
            "/api/pilot/v1/chat/completions",
            json={"model": "test", "messages": [{"role": "user", "content": "hi"}]},
            headers={"X-Business14-Provider-Key": "sk-real-key-12345abcdef"},
        )
        self._assert_invalid_registry_error(resp, "chat")

    def test_ui_get_no_leakage(self, _apply_invalid_registry):
        resp = _apply_invalid_registry.get("/pilot")
        assert resp.status_code == 200
        self._assert_no_leakage(resp.text, "ui_get")
        assert "registry_invalid" in resp.text

    def test_ui_post_no_leakage(self, _apply_invalid_registry):
        resp = _apply_invalid_registry.post(
            "/pilot",
            data={"provider_key": "sk-real-key", "prompt": "hello"},
        )
        assert resp.status_code == 200
        self._assert_no_leakage(resp.text, "ui_post")
        assert "registry_invalid" in resp.text or "올바르지 않습니다" in resp.text


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
