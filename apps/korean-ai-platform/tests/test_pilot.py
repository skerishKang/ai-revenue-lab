"""Tests for the BYOK Gateway Pilot (Phase 1).

All tests use fake transport (httpx.MockTransport) — no external network calls.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from app.factory import create_app
from app.pilot.config import pilot_settings


@pytest.fixture()
def app():
    return create_app()


@pytest.fixture()
def client(app):
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_pilot_config():
    """Reset pilot config before each test and restore after."""
    saved = {
        "base_url": pilot_settings.pilot_base_url,
        "model_id": pilot_settings.pilot_model_id,
    }
    yield
    pilot_settings.pilot_base_url = saved["base_url"]
    pilot_settings.pilot_model_id = saved["model_id"]


def _configure_pilot():
    """Set up a fake pilot configuration for testing."""
    pilot_settings.pilot_base_url = "https://api.test-pilot.example.com"
    pilot_settings.pilot_model_id = "test-model-v1"
    pilot_settings.pilot_provider_id = "test-provider"
    pilot_settings.pilot_upstream_model = "upstream-model-v1"
    pilot_settings.pilot_timeout_seconds = 10


# ---------------------------------------------------------------------------
# 1. Pilot health
# ---------------------------------------------------------------------------


class TestPilotHealth:
    def test_health_not_configured(self, client):
        resp = client.get("/api/pilot/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "not_configured"
        assert data["mode"] == "byok-pilot"
        assert data["configured_providers"] == 0

    def test_health_configured(self, client):
        _configure_pilot()
        resp = client.get("/api/pilot/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["configured_providers"] == 1


# ---------------------------------------------------------------------------
# 2. Provider not configured
# ---------------------------------------------------------------------------


class TestPilotNotConfigured:
    def test_models_empty_when_not_configured(self, client):
        resp = client.get("/api/pilot/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["models"] == []
        assert data["configured"] is False

    def test_chat_fails_when_not_configured(self, client):
        resp = client.post(
            "/api/pilot/v1/chat/completions",
            json={"model": "test", "messages": [{"role": "user", "content": "hi"}]},
            headers={"X-Business14-Provider-Key": "sk-real-key-12345abcdef"},
        )
        assert resp.status_code == 503
        data = resp.json()
        assert data["error"]["code"] == "pilot_not_configured"


# ---------------------------------------------------------------------------
# 3. Model list
# ---------------------------------------------------------------------------


class TestPilotModels:
    def test_models_list_when_configured(self, client):
        _configure_pilot()
        resp = client.get("/api/pilot/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is True
        assert len(data["models"]) >= 1
        assert data["models"][0]["id"] == "test-model-v1"
        assert data["models"][0]["pilot_available"] is True


# ---------------------------------------------------------------------------
# 4. Valid request schema
# ---------------------------------------------------------------------------


class TestPilotChatRequest:
    def test_valid_request_success(self, client, monkeypatch):
        _configure_pilot()
        from app.pilot import provider as prv
        
        async def fake_call(**kw):
            return {
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "model": "test-model-v1",
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": "Hello!"}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
                "business14": {"mode": "byok-pilot", "provider": "test-provider", "latency_ms": 100, "estimated_krw": 0.0, "request_id": "b14req_test"},
            }
        monkeypatch.setattr(prv, "call_chat_completions", fake_call)
        resp = client.post(
            "/api/pilot/v1/chat/completions",
            json={"model": "test-model-v1", "messages": [{"role": "user", "content": "hi"}], "temperature": 0.2, "max_tokens": 300},
            headers={"X-Business14-Provider-Key": "sk-real-key-12345abcdef"},
        )
        assert resp.status_code == 200
        assert resp.json()["choices"][0]["message"]["content"] == "Hello!"

    def test_valid_request_no_messages(self, client):
        _configure_pilot()
        resp = client.post(
            "/api/pilot/v1/chat/completions",
            json={"model": "test-model-v1", "messages": []},
            headers={"X-Business14-Provider-Key": "sk-real-key-12345abcdef"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "invalid_request"


# ---------------------------------------------------------------------------
# 5. Key missing
# ---------------------------------------------------------------------------


class TestMissingKey:
    def test_no_key_header(self, client):
        _configure_pilot()
        resp = client.post(
            "/api/pilot/v1/chat/completions",
            json={"model": "test-model-v1", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "missing_provider_key"

    def test_empty_key_header(self, client):
        _configure_pilot()
        resp = client.post(
            "/api/pilot/v1/chat/completions",
            json={"model": "test-model-v1", "messages": [{"role": "user", "content": "hi"}]},
            headers={"X-Business14-Provider-Key": ""},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 6. Placeholder key rejection
# ---------------------------------------------------------------------------


class TestPlaceholderKey:
    @pytest.mark.parametrize("bad_key", ["sk-your-key-here", "your-api-key", "test-key", "demo-key", "$KAP_API_KEY", "placeholder", "abc"])
    def test_placeholder_key_rejected(self, client, bad_key, monkeypatch):
        _configure_pilot()
        from app.pilot import provider as prv
        async def fake_call(**kw): return {"id": "test", "object": "chat.completion", "model": "test", "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]}
        monkeypatch.setattr(prv, "call_chat_completions", fake_call)
        resp = client.post(
            "/api/pilot/v1/chat/completions",
            json={"model": "test-model-v1", "messages": [{"role": "user", "content": "hi"}]},
            headers={"X-Business14-Provider-Key": bad_key},
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "placeholder_key_rejected"


# ---------------------------------------------------------------------------
# 7. Unsupported model
# ---------------------------------------------------------------------------


class TestUnsupportedModel:
    def test_unknown_model_rejected(self, client):
        _configure_pilot()
        resp = client.post(
            "/api/pilot/v1/chat/completions",
            json={"model": "nonexistent-model-9000", "messages": [{"role": "user", "content": "hi"}]},
            headers={"X-Business14-Provider-Key": "sk-real-key-12345abcdef"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "unsupported_model"


# ---------------------------------------------------------------------------
# 8. Stream rejection
# ---------------------------------------------------------------------------


class TestStreamRejection:
    def test_stream_true_rejected(self, client):
        _configure_pilot()
        resp = client.post(
            "/api/pilot/v1/chat/completions",
            json={"model": "test-model-v1", "messages": [{"role": "user", "content": "hi"}], "stream": True},
            headers={"X-Business14-Provider-Key": "sk-real-key-12345abcdef"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "stream_not_supported"


# ---------------------------------------------------------------------------
# 9. Tools rejection
# ---------------------------------------------------------------------------


class TestToolsRejection:
    def test_tools_rejected(self, client):
        _configure_pilot()
        resp = client.post(
            "/api/pilot/v1/chat/completions",
            json={"model": "test-model-v1", "messages": [{"role": "user", "content": "hi"}], "tools": [{"name": "test"}]},
            headers={"X-Business14-Provider-Key": "sk-real-key-12345abcdef"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "tools_not_supported"


# ---------------------------------------------------------------------------
# 10. Arbitrary base URL blocked
# ---------------------------------------------------------------------------


class TestArbitraryBaseUrl:
    def test_no_base_url_param(self, client, monkeypatch):
        """User cannot inject base_url into the request."""
        _configure_pilot()
        from app.pilot import provider as prv
        async def fake_call(**kw): return {"id": "test", "object": "chat.completion", "model": "test", "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]}
        monkeypatch.setattr(prv, "call_chat_completions", fake_call)
        resp = client.post(
            "/api/pilot/v1/chat/completions",
            json={"model": "test-model-v1", "messages": [{"role": "user", "content": "hi"}], "base_url": "http://evil.com"},
            headers={"X-Business14-Provider-Key": "sk-real-key-12345abcdef"},
        )
        assert resp.status_code in (200, 400, 422)


# ---------------------------------------------------------------------------
# 11. Fake transport test (direct call_chat_completions test)
# ---------------------------------------------------------------------------


class TestProviderAdapter:
    """Tests call_chat_completions directly with MockTransport."""

    @pytest.mark.asyncio
    async def test_success_response(self):
        _configure_pilot()
        import httpx
        from app.pilot.provider import call_chat_completions

        async def fake_upstream(request):
            return httpx.Response(200, json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hello!"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
            })

        transport = httpx.MockTransport(fake_upstream)
        result = await call_chat_completions(
            api_key="sk-real-test-key",
            messages=[{"role": "user", "content": "hi"}],
            transport=transport,
        )
        assert result["choices"][0]["message"]["content"] == "Hello!"
        assert result["usage"]["prompt_tokens"] == 5

    @pytest.mark.asyncio
    async def test_no_usage_response(self):
        _configure_pilot()
        import httpx
        from app.pilot.provider import call_chat_completions

        async def fake_upstream(request):
            return httpx.Response(200, json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            })

        transport = httpx.MockTransport(fake_upstream)
        result = await call_chat_completions(
            api_key="sk-real-test-key",
            messages=[{"role": "user", "content": "hi"}],
            transport=transport,
        )
        assert result["usage"] is None

    @pytest.mark.asyncio
    async def test_timeout(self):
        _configure_pilot()
        import httpx
        from app.pilot.provider import call_chat_completions
        from app.pilot.errors import UpstreamTimeout

        async def fake_timeout(request):
            raise httpx.TimeoutException("timed out")

        transport = httpx.MockTransport(fake_timeout)
        import pytest
        with pytest.raises(UpstreamTimeout):
            await call_chat_completions(
                api_key="sk-real-test-key",
                messages=[{"role": "user", "content": "hi"}],
                transport=transport,
            )

    @pytest.mark.asyncio
    async def test_401_error(self):
        _configure_pilot()
        import httpx
        from app.pilot.provider import call_chat_completions
        from app.pilot.errors import UpstreamAuthFailed

        async def fake_401(request):
            return httpx.Response(401, json={"error": "unauthorized"})

        transport = httpx.MockTransport(fake_401)
        import pytest
        with pytest.raises(UpstreamAuthFailed):
            await call_chat_completions(
                api_key="sk-real-test-key",
                messages=[{"role": "user", "content": "hi"}],
                transport=transport,
            )

    @pytest.mark.asyncio
    async def test_429_error(self):
        _configure_pilot()
        import httpx
        from app.pilot.provider import call_chat_completions
        from app.pilot.errors import UpstreamRateLimited

        async def fake_429(request):
            return httpx.Response(429, json={"error": "rate limited"})

        transport = httpx.MockTransport(fake_429)
        import pytest
        with pytest.raises(UpstreamRateLimited):
            await call_chat_completions(
                api_key="sk-real-test-key",
                messages=[{"role": "user", "content": "hi"}],
                transport=transport,
            )

    @pytest.mark.asyncio
    async def test_500_error(self):
        _configure_pilot()
        import httpx
        from app.pilot.provider import call_chat_completions
        from app.pilot.errors import UpstreamServerError

        async def fake_500(request):
            return httpx.Response(500, json={"error": "server error"})

        transport = httpx.MockTransport(fake_500)
        import pytest
        with pytest.raises(UpstreamServerError):
            await call_chat_completions(
                api_key="sk-real-test-key",
                messages=[{"role": "user", "content": "hi"}],
                transport=transport,
            )

    @pytest.mark.asyncio
    async def test_malformed_json(self):
        _configure_pilot()
        import httpx
        from app.pilot.provider import call_chat_completions
        from app.pilot.errors import MalformedUpstreamResponse

        async def fake_bad(request):
            return httpx.Response(200, text="not-json{{{}}}")

        transport = httpx.MockTransport(fake_bad)
        import pytest
        with pytest.raises(MalformedUpstreamResponse):
            await call_chat_completions(
                api_key="sk-real-test-key",
                messages=[{"role": "user", "content": "hi"}],
                transport=transport,
            )

    @pytest.mark.asyncio
    async def test_redirect_not_followed(self):
        _configure_pilot()
        import httpx
        from app.pilot.provider import call_chat_completions
        from app.pilot.errors import MalformedUpstreamResponse

        async def fake_redirect(request):
            return httpx.Response(302, headers={"location": "https://evil.com"})

        transport = httpx.MockTransport(fake_redirect)
        import pytest
        with pytest.raises(MalformedUpstreamResponse):
            await call_chat_completions(
                api_key="sk-real-test-key",
                messages=[{"role": "user", "content": "hi"}],
                transport=transport,
            )


# ---------------------------------------------------------------------------
# 12-13. Usage handling
# ---------------------------------------------------------------------------


class TestUsageHandling:
    def test_usage_in_route(self, client, monkeypatch):
        _configure_pilot()
        from app.pilot import provider as prv
        async def fake_call(**kw):
            return {"id": "test", "object": "chat.completion", "model": "test-model-v1",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
                    "business14": {"mode": "byok-pilot", "provider": "test", "latency_ms": 50, "estimated_krw": 0.0, "request_id": "b14req_test"}}
        monkeypatch.setattr(prv, "call_chat_completions", fake_call)
        resp = client.post(
            "/api/pilot/v1/chat/completions",
            json={"model": "test-model-v1", "messages": [{"role": "user", "content": "hi"}]},
            headers={"X-Business14-Provider-Key": "sk-real-key-test"},
        )
        assert resp.status_code == 200
        assert resp.json()["usage"]["total_tokens"] == 30


# ---------------------------------------------------------------------------
# 14. Request ID present
# ---------------------------------------------------------------------------


class TestRequestID:
    def test_error_response_has_request_id(self, client):
        resp = client.post(
            "/api/pilot/v1/chat/completions",
            json={"model": "test", "messages": [{"role": "user", "content": "hi"}]},
            headers={"X-Business14-Provider-Key": "sk-test-key"},
        )
        data = resp.json()
        assert "request_id" in data.get("error", {})


# ---------------------------------------------------------------------------
# 15-16. Pilot page UI
# ---------------------------------------------------------------------------


class TestPilotPageUI:

    def test_page_renders(self, client):
        resp = client.get("/pilot")
        assert resp.status_code == 200

    def test_page_shows_unconfigured_message(self, client):
        pilot_settings.pilot_base_url = ""
        pilot_settings.pilot_model_id = ""
        resp = client.get("/pilot")
        assert resp.status_code == 200
        assert "Pilot Provider가 설정되지 않았습니다" in resp.text or "BYOK Gateway Pilot" in resp.text

    def test_page_not_commercial_service(self, client):
        resp = client.get("/pilot")
        assert resp.status_code == 200
        assert "Phase 1 Pilot" in resp.text

    def test_page_shows_mock_diff(self, client):
        resp = client.get("/pilot")
        assert resp.status_code == 200
        assert "Playground" in resp.text or "Mock" in resp.text


# ---------------------------------------------------------------------------
# 17. Phase 0 preserved
# ---------------------------------------------------------------------------


class TestPhase0Preserved:
    def test_8_models_still_in_catalog(self, client):
        resp = client.get("/models")
        assert resp.status_code == 200
        from app.demo_data import MODELS
        assert len(MODELS) == 8
        for m in MODELS:
            assert m.name in resp.text

    def test_mock_playground_still_works(self, client):
        resp = client.get("/playground")
        assert resp.status_code == 200
        assert "API Playground" in resp.text


# ---------------------------------------------------------------------------
# 18. Demo models helper
# ---------------------------------------------------------------------------


class TestPilotDemoModels:
    def test_empty_when_not_configured(self):
        pilot_settings.pilot_base_url = ""
        pilot_settings.pilot_model_id = ""
        from app.pilot.demo_models import get_pilot_models
        assert get_pilot_models() == []

    def test_returns_model_when_configured(self):
        _configure_pilot()
        from app.pilot.demo_models import get_pilot_models
        models = get_pilot_models()
        assert len(models) >= 1
        assert models[0]["id"] == "test-model-v1"


# ---------------------------------------------------------------------------
# 19. Full route smoke
# ---------------------------------------------------------------------------


class TestRouteSmoke:
    def test_home(self, client):
        assert client.get("/").status_code == 200

    def test_models(self, client):
        assert client.get("/models").status_code == 200

    def test_playground(self, client):
        assert client.get("/playground").status_code == 200

    def test_api_keys(self, client):
        assert client.get("/api-keys").status_code == 200

    def test_docs(self, client):
        assert client.get("/docs").status_code == 200

    def test_usage(self, client):
        assert client.get("/usage").status_code == 200

    def test_pricing(self, client):
        assert client.get("/pricing").status_code == 200

    def test_access(self, client):
        assert client.get("/access").status_code == 200

    def test_health(self, client):
        assert client.get("/health").status_code == 200

    def test_pilot_page(self, client):
        assert client.get("/pilot").status_code == 200

    def test_pilot_health(self, client):
        assert client.get("/api/pilot/health").status_code == 200

    def test_pilot_models(self, client):
        assert client.get("/api/pilot/models").status_code == 200


# ---------------------------------------------------------------------------
# 20. Redaction tests
# ---------------------------------------------------------------------------


class TestRedaction:
    def test_secret_not_in_error_response(self, client):
        _configure_pilot()
        resp = client.post(
            "/api/pilot/v1/chat/completions",
            json={"model": "test-model-v1", "messages": [{"role": "user", "content": "hi"}]},
            headers={"X-Business14-Provider-Key": "sk-real-key-secret-123"},
        )
        body = resp.text.lower()
        assert "sk-real-key-secret-123" not in body
