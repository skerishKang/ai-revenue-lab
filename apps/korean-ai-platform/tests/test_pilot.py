"""Tests for the BYOK Gateway Pilot (Phase 1).

All tests use fake transport (httpx.MockTransport) — no external network calls.
"""

from __future__ import annotations

import httpx
import pytest
from starlette.testclient import TestClient
from app.pilot.schemas import ValidationError

from app.factory import create_app
from app.pilot.config import pilot_settings
from app.pilot.schemas import ChatMessage, PilotChatRequest

from _pilot_lane_paths import chat_surface
from tests._registry_values import a_provider_id, model_rows, registry


# The gateway surface these cases call. Its path is the app's, not this
# file's, so it is read back out of the mounted router.
CHAT_COMPLETIONS = chat_surface()


# A syntactically valid https origin for the legacy lane. It is not a real
# Provider host: every test stubs the transport, so nothing is ever dialed.
_PILOT_BASE_ORIGIN = "https://pilot.test.invalid/v1"


@pytest.fixture(autouse=True)
def _enable_archived_auto_route_tests(monkeypatch):
    """Historical protocol tests explicitly enable future generic auto in test only."""
    monkeypatch.setenv("B14_ENABLE_FUTURE_AUTO", "1")



@pytest.fixture()
def app():
    return create_app()


@pytest.fixture()
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _reset_pilot_config(monkeypatch):
    saved = {
        "base_url": pilot_settings.pilot_base_url,
        "model_id": pilot_settings.pilot_model_id,
        "registry_json": pilot_settings.provider_registry_json,
    }
    # B14 gateway is live-ready via the keyless Kilo route whenever
    # B14_PROVIDER_MODE=live (#1933 S2). Force mock so legacy BYOK
    # not_configured assertions stay isolated from B14 mode leaks.
    monkeypatch.delenv("B14_PROVIDER_MODE", raising=False)
    from app.pilot.b14_runtime_config import runtime_config as rcfg

    saved_mode = rcfg.provider_mode
    rcfg.provider_mode = "mock"
    yield
    pilot_settings.pilot_base_url = saved["base_url"]
    pilot_settings.pilot_model_id = saved["model_id"]
    pilot_settings.provider_registry_json = saved["registry_json"]
    rcfg.provider_mode = saved_mode


def _pilot_identity() -> tuple[str, str, str]:
    """The (provider, model, upstream) identity the legacy BYOK lane serves.

    The BYOK lane carries a caller's own model, so its identity must be one the
    Business 14 catalog does *not* know: any retired identity qualifies, because
    a retirement always wins over a registration. The Provider is the effective
    registry's first Provider, whose origin the configured base URL mirrors.
    """
    from app.pilot.catalog import get_catalog_by_id
    from app.pilot.model_registry_file import retired_model_ids

    provider_id = a_provider_id()
    model_id = next(
        (rid for rid in sorted(retired_model_ids()) if get_catalog_by_id(rid) is None),
        None,
    )
    assert model_id is not None, "the registry must retire at least one identity"
    return provider_id, model_id, model_id


def _configure_pilot():
    provider_id, model_id, upstream = _pilot_identity()
    pilot_settings.pilot_base_url = _PILOT_BASE_ORIGIN
    pilot_settings.pilot_model_id = model_id
    pilot_settings.pilot_provider_id = provider_id
    pilot_settings.pilot_upstream_model = upstream
    pilot_settings.pilot_timeout_seconds = 10
    pilot_settings.provider_registry_json = ""
    return model_id


# ---------------------------------------------------------------------------
# Health and config
# ---------------------------------------------------------------------------


class TestPilotHealth:
    def test_health_not_configured(self, client):
        resp = client.get("/api/pilot/admin/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "not_configured"
        assert data["configured_providers"] == 0

    def test_health_configured(self, client):
        _configure_pilot()
        resp = client.get("/api/pilot/admin/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["configured_providers"] == 1


class TestPilotNotConfigured:
    def test_models_empty_when_not_configured(self, client):
        resp = client.get("/api/pilot/admin/models")
        assert resp.status_code == 200
        assert resp.json()["models"] == []

    def test_chat_fails_when_not_configured(self, client):
        resp = client.post(
            CHAT_COMPLETIONS,
            json={"model": "test", "messages": [{"role": "user", "content": "hi"}]},
            headers={"X-Business14-Provider-Key": "sk-real-key-12345abcdef"},
        )
        assert resp.status_code == 503
        assert resp.json()["error"]["code"] == "pilot_not_configured"


class TestPilotModels:
    def test_models_list_when_configured(self, client):
        _configure_pilot()
        resp = client.get("/api/pilot/admin/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is True
        assert len(data["models"]) >= 1
        assert data["models"][0]["pilot_available"] is True


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


class TestSchemaValidation:
    def test_extra_fields_forbidden(self):
        """Unknown fields should be rejected by dataclass."""
        with pytest.raises(TypeError):
            PilotChatRequest(model="test", messages=[ChatMessage(role="user", content="hi")], base_url="http://evil.com")

    def test_api_key_field_forbidden(self):
        with pytest.raises(TypeError):
            PilotChatRequest(model="test", messages=[ChatMessage(role="user", content="hi")], api_key="sk-test")

    def test_endpoint_field_forbidden(self):
        with pytest.raises(TypeError):
            PilotChatRequest(model="test", messages=[ChatMessage(role="user", content="hi")], endpoint="http://evil.com")

    def test_invalid_role(self):
        with pytest.raises(ValidationError):
            ChatMessage(role="admin", content="hi")

    def test_empty_content(self):
        with pytest.raises(ValidationError):
            ChatMessage(role="user", content="   ")

    def test_content_too_long(self):
        with pytest.raises(ValidationError):
            ChatMessage(role="user", content="x" * 33000)

    def test_empty_model(self):
        with pytest.raises(ValidationError):
            PilotChatRequest(model="", messages=[ChatMessage(role="user", content="hi")])

    def test_temperature_too_high(self):
        with pytest.raises(ValidationError):
            PilotChatRequest(model="test", messages=[ChatMessage(role="user", content="hi")], temperature=3.0)

    def test_temperature_negative(self):
        with pytest.raises(ValidationError):
            PilotChatRequest(model="test", messages=[ChatMessage(role="user", content="hi")], temperature=-0.1)

    def test_max_tokens_too_high(self):
        with pytest.raises(ValidationError):
            PilotChatRequest(model="test", messages=[ChatMessage(role="user", content="hi")], max_tokens=2147483648)

    def test_max_tokens_zero(self):
        with pytest.raises(ValidationError):
            PilotChatRequest(model="test", messages=[ChatMessage(role="user", content="hi")], max_tokens=0)

    def test_no_messages(self):
        with pytest.raises(ValidationError):
            PilotChatRequest(model="test", messages=[])

    def test_too_many_messages(self):
        with pytest.raises(ValidationError):
            PilotChatRequest(model="test", messages=[ChatMessage(role="user", content="x")] * 101)


class TestExtraFieldsRejectedViaAPI:
    def test_base_url_rejected(self, client):
        model = _configure_pilot()
        resp = client.post(
            CHAT_COMPLETIONS,
            json={"model": model, "messages": [{"role": "user", "content": "hi"}], "base_url": "http://evil.com"},
            headers={"X-Business14-Provider-Key": "sk-real-key-12345abcdef"},
        )
        assert resp.status_code == 422

    def test_api_key_field_rejected(self, client):
        model = _configure_pilot()
        resp = client.post(
            CHAT_COMPLETIONS,
            json={"model": model, "messages": [{"role": "user", "content": "hi"}], "api_key": "sk-test"},
            headers={"X-Business14-Provider-Key": "sk-real-key-12345abcdef"},
        )
        assert resp.status_code == 422

    def test_invalid_role_rejected(self, client):
        model = _configure_pilot()
        resp = client.post(
            CHAT_COMPLETIONS,
            json={"model": model, "messages": [{"role": "admin", "content": "hi"}]},
            headers={"X-Business14-Provider-Key": "sk-real-key-12345abcdef"},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Request validation
# ---------------------------------------------------------------------------


class TestPilotChatRequest:
    def test_valid_request(self, client, monkeypatch):
        model = _configure_pilot()
        from app.pilot import provider as prv
        async def fake_call(**kw):
            return {"id": "test", "object": "chat.completion", "model": model,
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hello!"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
                    "business14": {"mode": "byok-pilot", "provider": "test", "latency_ms": 100, "estimated_krw": None, "request_id": "b14req_test"}}
        monkeypatch.setattr(prv, "call_chat_completions", fake_call)
        resp = client.post(
            CHAT_COMPLETIONS,
            json={"model": model, "messages": [{"role": "user", "content": "hi"}], "temperature": 0.2, "max_tokens": 300},
            headers={"X-Business14-Provider-Key": "sk-real-key-12345abcdef"},
        )
        assert resp.status_code == 200
        assert resp.json()["choices"][0]["message"]["content"] == "Hello!"
        # Cost metadata must be None (unknown, not free)
        assert resp.json()["business14"]["estimated_krw"] is None

    def test_no_messages(self, client):
        model = _configure_pilot()
        resp = client.post(
            CHAT_COMPLETIONS,
            json={"model": model, "messages": []},
            headers={"X-Business14-Provider-Key": "sk-real-key-12345abcdef"},
        )
        assert resp.status_code == 422

    def test_stream_true_rejected(self, client):
        model = _configure_pilot()
        resp = client.post(
            CHAT_COMPLETIONS,
            json={"model": model, "messages": [{"role": "user", "content": "hi"}], "stream": True},
            headers={"X-Business14-Provider-Key": "sk-real-key-12345abcdef"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "stream_not_supported"

    def test_tools_rejected(self, client):
        # #5536: the BYOK lane serves a caller's own provider and model, and
        # B14 holds no capability record for it, so a tool declaration is
        # refused there rather than forwarded unverified.
        model = _configure_pilot()
        resp = client.post(
            CHAT_COMPLETIONS,
            json={
                "model": model,
                "messages": [{"role": "user", "content": "hi"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "generateSandboxedUi",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ],
            },
            headers={"X-Business14-Provider-Key": "sk-real-key-12345abcdef"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "tools_not_supported"

    def test_malformed_tool_declaration_rejected(self, client):
        # #5536: a malformed tool declaration is refused before any provider
        # call, so it never spends a credential.
        model = _configure_pilot()
        resp = client.post(
            CHAT_COMPLETIONS,
            json={"model": model, "messages": [{"role": "user", "content": "hi"}], "tools": [{"name": "test"}]},
            headers={"X-Business14-Provider-Key": "sk-real-key-12345abcdef"},
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "invalid_body"

    def test_unknown_model_rejected(self, client):
        _configure_pilot()
        resp = client.post(
            CHAT_COMPLETIONS,
            json={"model": "nonexistent", "messages": [{"role": "user", "content": "hi"}]},
            headers={"X-Business14-Provider-Key": "sk-real-key-12345abcdef"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "unsupported_model"


# ---------------------------------------------------------------------------
# Key validation
# ---------------------------------------------------------------------------


class TestMissingKey:
    def test_no_key_header(self, client):
        model = _configure_pilot()
        resp = client.post(
            CHAT_COMPLETIONS,
            json={"model": model, "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "missing_provider_key"


class TestPlaceholderKey:
    @pytest.mark.parametrize("bad_key", ["sk-your-key-here", "your-api-key", "test-key", "demo-key", "$KAP_API_KEY", "placeholder", "abc"])
    def test_placeholder_key_rejected(self, client, bad_key, monkeypatch):
        model = _configure_pilot()
        from app.pilot import provider as prv
        async def fake_call(**kw): return {"id": "test", "object": "chat.completion", "model": "test", "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]}
        monkeypatch.setattr(prv, "call_chat_completions", fake_call)
        resp = client.post(
            CHAT_COMPLETIONS,
            json={"model": model, "messages": [{"role": "user", "content": "hi"}]},
            headers={"X-Business14-Provider-Key": bad_key},
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "placeholder_key_rejected"


# ---------------------------------------------------------------------------
# Temperature default value test
# ---------------------------------------------------------------------------


class TestDefaultTemperature:
    def test_ui_form_defaults_to_provider_native(self, client):
        """Do not force a sampling default in the form."""
        _configure_pilot()
        resp = client.get("/pilot")
        assert resp.status_code == 200
        assert 'id="pilot_temp" name="temperature"' in resp.text
        assert 'name="temperature" min="0" max="2" step="0.1" value=""' in resp.text
        assert 'max="2"' in resp.text
        assert 'step="0.1"' in resp.text

    def test_ui_post_passes_02(self, client, monkeypatch):
        """UI POST with default temperature must pass 0.2 to provider."""
        model = _configure_pilot()
        from app.pilot import provider as prv
        _captured = {}

        async def capturing_call(**kw):
            _captured["temperature"] = kw.get("temperature")
            return {
                "id": "test", "object": "chat.completion", "model": model,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
                "business14": {"mode": "byok-pilot", "provider": "test", "latency_ms": 50, "estimated_krw": None, "request_id": "b14req_test"},
            }

        monkeypatch.setattr(prv, "call_chat_completions", capturing_call)
        resp = client.post(
            "/pilot",
            data={
                "provider_key": "sk-real-key-12345abcdef",
                "model_id": model,
                "prompt": "hello",
                "temperature": 0.2,
                "max_tokens": 300,
            },
        )
        assert resp.status_code == 200
        assert _captured.get("temperature") == 0.2


# ---------------------------------------------------------------------------
# Error redaction tests
# ---------------------------------------------------------------------------


class TestErrorRedaction:
    def test_api_error_has_fixed_message(self, client, monkeypatch):
        """Generic exception should show fixed message, not str(e)."""
        model = _configure_pilot()
        from app.pilot import provider as prv
        class ExplodingError(Exception):
            def __str__(self):
                return "SECRET_KEY=sk-abcdef1234567890"

        async def exploding_call(**kw):
            raise ExplodingError()

        monkeypatch.setattr(prv, "call_chat_completions", exploding_call)
        resp = client.post(
            CHAT_COMPLETIONS,
            json={"model": model, "messages": [{"role": "user", "content": "hi"}]},
            headers={"X-Business14-Provider-Key": "sk-real-key-12345abcdef"},
        )
        body = resp.text
        assert "sk-abcdef1234567890" not in body
        assert "SECRET_KEY" not in body
        assert resp.json()["error"]["message"] == "요청을 처리하는 중 내부 오류가 발생했습니다. Request ID로 관리자에게 문의하십시오."

    def test_json_body_uses_explicit_asgi_body_boundary(self, client, monkeypatch):
        """The gateway must not depend on Starlette Request.json() in Workers."""
        from app.pilot import gateway
        from app.pilot.catalog import get_catalog_by_id
        from app.pilot.platform_secrets import get_platform_provider

        # A catalog model whose platform Provider keeps its credential in a
        # platform secret: the slot name comes from the Provider's own spec.
        model_id = next(
            row["id"]
            for row in model_rows()
            if (model := get_catalog_by_id(row["id"])) is not None
            and (spec := get_platform_provider(model.platform_provider_id)) is not None
            and getattr(spec.credential_source, "value", spec.credential_source) == "platform_secret"
        )
        spec = get_platform_provider(get_catalog_by_id(model_id).platform_provider_id)
        monkeypatch.setenv(spec.credential_binding_name, "sk-test-route-0123456789")
        original = gateway.Request.json

        async def broken_json(_request):
            raise RuntimeError("convenience json bridge unavailable")

        monkeypatch.setattr(gateway.Request, "json", broken_json)
        response = client.post(
            "/api/pilot/router/resolve",
            json={"model": model_id, "messages": [{"role": "user", "content": "hi"}]},
        )
        assert response.status_code == 200
        assert response.json()["selected_model"]
        monkeypatch.setattr(gateway.Request, "json", original)

    def test_api_error_has_request_id(self, client):
        _configure_pilot()
        resp = client.post(
            CHAT_COMPLETIONS,
            json={"model": "test", "messages": [{"role": "user", "content": "hi"}]},
            headers={"X-Business14-Provider-Key": "sk-test-key"},
        )
        assert resp.json()["error"].get("request_id", "").startswith("b14req_")

    def test_secret_not_in_error_response(self, client, monkeypatch):
        model = _configure_pilot()
        from app.pilot import provider as prv
        async def fake_call(**kw): raise Exception("sk-real-key-secret-123")
        monkeypatch.setattr(prv, "call_chat_completions", fake_call)
        resp = client.post(
            CHAT_COMPLETIONS,
            json={"model": model, "messages": [{"role": "user", "content": "hi"}]},
            headers={"X-Business14-Provider-Key": "sk-real-key-secret-123"},
        )
        assert "sk-real-key-secret-123" not in resp.text


# ---------------------------------------------------------------------------
# Provider adapter tests (direct call)
# ---------------------------------------------------------------------------


class TestProviderAdapter:
    @pytest.mark.asyncio
    async def test_success_response(self):
        _configure_pilot()
        from app.pilot.provider import call_chat_completions
        async def fake_upstream(request):
            return httpx.Response(200, json={
                "id": "chatcmpl-test", "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hello!"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
            })
        result = await call_chat_completions(api_key="sk-test", messages=[{"role": "user", "content": "hi"}], transport=httpx.MockTransport(fake_upstream))
        assert result["usage"]["total_tokens"] == 15

    @pytest.mark.asyncio
    async def test_no_usage(self):
        _configure_pilot()
        from app.pilot.provider import call_chat_completions
        async def fake_upstream(request):
            return httpx.Response(200, json={
                "id": "chatcmpl-test", "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            })
        result = await call_chat_completions(api_key="sk-test", messages=[{"role": "user", "content": "hi"}], transport=httpx.MockTransport(fake_upstream))
        assert result["usage"] is None

    @pytest.mark.asyncio
    async def test_timeout(self):
        _configure_pilot()
        from app.pilot.provider import call_chat_completions
        from app.pilot.errors import UpstreamTimeout
        async def fake_timeout(request):
            raise httpx.TimeoutException("timed out")
        with pytest.raises(UpstreamTimeout):
            await call_chat_completions(api_key="sk-test", messages=[{"role": "user", "content": "hi"}], transport=httpx.MockTransport(fake_timeout))

    @pytest.mark.asyncio
    async def test_401_error(self):
        _configure_pilot()
        from app.pilot.provider import call_chat_completions
        from app.pilot.errors import UpstreamAuthFailed
        async def fake_401(request):
            return httpx.Response(401, json={"error": "unauthorized"})
        with pytest.raises(UpstreamAuthFailed):
            await call_chat_completions(api_key="sk-test", messages=[{"role": "user", "content": "hi"}], transport=httpx.MockTransport(fake_401))

    @pytest.mark.asyncio
    async def test_403_error(self):
        _configure_pilot()
        from app.pilot.provider import call_chat_completions
        from app.pilot.errors import UpstreamAuthFailed
        async def fake_403(request):
            return httpx.Response(403, json={"error": "forbidden"})
        with pytest.raises(UpstreamAuthFailed):
            await call_chat_completions(api_key="sk-test", messages=[{"role": "user", "content": "hi"}], transport=httpx.MockTransport(fake_403))

    @pytest.mark.asyncio
    async def test_404_error(self):
        _configure_pilot()
        from app.pilot.provider import call_chat_completions
        from app.pilot.errors import UpstreamServerError
        async def fake_404(request):
            return httpx.Response(404, json={"error": "not found"})
        with pytest.raises(UpstreamServerError):
            await call_chat_completions(api_key="sk-test", messages=[{"role": "user", "content": "hi"}], transport=httpx.MockTransport(fake_404))

    @pytest.mark.asyncio
    async def test_429_error(self):
        _configure_pilot()
        from app.pilot.provider import call_chat_completions
        from app.pilot.errors import UpstreamRateLimited
        async def fake_429(request):
            return httpx.Response(429, json={"error": "rate limited"})
        with pytest.raises(UpstreamRateLimited):
            await call_chat_completions(api_key="sk-test", messages=[{"role": "user", "content": "hi"}], transport=httpx.MockTransport(fake_429))

    @pytest.mark.asyncio
    async def test_500_error(self):
        _configure_pilot()
        from app.pilot.provider import call_chat_completions
        from app.pilot.errors import UpstreamServerError
        async def fake_500(request):
            return httpx.Response(500, json={"error": "server error"})
        with pytest.raises(UpstreamServerError):
            await call_chat_completions(api_key="sk-test", messages=[{"role": "user", "content": "hi"}], transport=httpx.MockTransport(fake_500))

    @pytest.mark.asyncio
    async def test_malformed_json(self):
        _configure_pilot()
        from app.pilot.provider import call_chat_completions
        from app.pilot.errors import MalformedUpstreamResponse
        async def fake_bad(request):
            return httpx.Response(200, text="not-json{{{}}}")
        with pytest.raises(MalformedUpstreamResponse):
            await call_chat_completions(api_key="sk-test", messages=[{"role": "user", "content": "hi"}], transport=httpx.MockTransport(fake_bad))

    @pytest.mark.asyncio
    async def test_redirect(self):
        _configure_pilot()
        from app.pilot.provider import call_chat_completions
        from app.pilot.errors import MalformedUpstreamResponse
        async def fake_redirect(request):
            return httpx.Response(302, headers={"location": "https://evil.com"})
        with pytest.raises(MalformedUpstreamResponse):
            await call_chat_completions(api_key="sk-test", messages=[{"role": "user", "content": "hi"}], transport=httpx.MockTransport(fake_redirect))


# ---------------------------------------------------------------------------
# SSRF validation tests
# ---------------------------------------------------------------------------


class TestSSRFValidation:
    @pytest.mark.parametrize("bad_url", [
        "http://api.example.com/v1",  # http, not https
        "https://localhost:8000/v1",
        "https://127.0.0.1:8000/v1",
        "https://10.0.0.1/v1",
        "https://192.168.1.1/v1",
        "https://172.16.0.1/v1",
        "https://169.254.1.1/v1",
        "https://[::1]:8000/v1",
        "https://[fc00::1]/v1",
        "https://[fe80::1]/v1",
        "https://user:pass@api.example.com/v1",
        "https://0.0.0.0/v1",
    ])
    def test_invalid_urls_rejected(self, bad_url):
        from app.pilot.provider import _validate_base_url
        with pytest.raises(ValueError):
            _validate_base_url(bad_url)

    @pytest.mark.parametrize("good_url", [
        # The Provider origins the registry documents; the validator must accept
        # every one of them, so the case set follows the document.
        *sorted(
            entry["base_origin"]
            for entry in registry()["providers"].values()
            if entry.get("base_origin")
        ),
        "https://gateway.example.com/chat",
    ])
    def test_valid_urls_accepted(self, good_url):
        from app.pilot.provider import _validate_base_url
        _validate_base_url(good_url)


# ---------------------------------------------------------------------------
# Redaction tests
# ---------------------------------------------------------------------------


class TestRedaction:
    def test_redact_sensitive_removes_sk(self):
        from app.pilot.redaction import redact_sensitive
        assert "[REDACTED]" in redact_sensitive("sk-abc12345def67890ghijklmnop")

    def test_redact_sensitive_removes_bearer(self):
        from app.pilot.redaction import redact_sensitive
        assert "[REDACTED]" in redact_sensitive("Bearer sk-abc12345")


# ---------------------------------------------------------------------------
# UI page tests
# ---------------------------------------------------------------------------


class TestPilotPageUI:
    def test_page_renders(self, client):
        assert client.get("/pilot").status_code == 200

    def test_page_not_commercial_service(self, client):
        resp = client.get("/pilot")
        assert "Phase 2 Pilot" in resp.text or "BYOK Gateway Pilot" in resp.text

    def test_page_shows_unconfigured_message(self, client):
        resp = client.get("/pilot")
        assert "Pilot Provider가 설정되지 않았습니다" in resp.text or "BYOK Gateway Pilot" in resp.text


# ---------------------------------------------------------------------------
# Pilot demo models
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
        assert len(get_pilot_models()) >= 1


# ---------------------------------------------------------------------------
# Phase 0 preservation
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
        assert client.get("/playground").status_code == 200


# ---------------------------------------------------------------------------
# Route smoke
# ---------------------------------------------------------------------------


class TestRouteSmoke:
    def test_home(self, client): assert client.get("/").status_code == 200
    def test_models(self, client): assert client.get("/models").status_code == 200
    def test_playground(self, client): assert client.get("/playground").status_code == 200
    def test_api_keys(self, client): assert client.get("/api-keys").status_code == 200
    def test_docs(self, client): assert client.get("/docs").status_code == 200
    def test_usage(self, client): assert client.get("/usage").status_code == 200
    def test_pricing(self, client): assert client.get("/pricing").status_code == 200
    def test_access(self, client): assert client.get("/access").status_code == 200
    def test_health(self, client): assert client.get("/health").status_code == 200
    def test_pilot(self, client): assert client.get("/pilot").status_code == 200
    def test_pilot_health(self, client): assert client.get("/api/pilot/admin/health").status_code == 200
    def test_pilot_models(self, client): assert client.get("/api/pilot/admin/models").status_code == 200


# ---------------------------------------------------------------------------
# Integration tests: full API route → Provider adapter → MockTransport
# ---------------------------------------------------------------------------


class TestIntegrationFullPath:
    """Full-path integration tests: HTTP route → real provider → MockTransport."""

    def test_api_route_integration(self, client):
        """API route → real provider → MockTransport → 200 + JSON verification."""
        model = _configure_pilot()
        captured_body = {}

        async def fake_upstream(request):
            import json
            captured_body["body"] = json.loads(request.read())
            return httpx.Response(200, json={
                "id": "chatcmpl-test", "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
            })

        transport = httpx.MockTransport(fake_upstream)
        from app.pilot import provider as prv
        original_call = prv.call_chat_completions

        async def patched_call(**kw):
            kw["transport"] = transport
            return await original_call(**kw)

        prv.call_chat_completions = patched_call
        try:
            resp = client.post(
                CHAT_COMPLETIONS,
                json={"model": model, "messages": [{"role": "user", "content": "hi"}]},
                headers={"X-Business14-Provider-Key": "sk-real-key-12345abcdef"},
            )
        finally:
            prv.call_chat_completions = original_call

        assert resp.status_code == 200
        body = captured_body.get("body", {})
        assert isinstance(body.get("messages"), list)
        if body.get("messages"):
            msg = body["messages"][0]
            assert isinstance(msg, dict), f"message must be dict, got {type(msg)}"
            assert msg == {"role": "user", "content": "hi"}

    def test_ui_post_integration(self, client):
        """UI POST → real provider → MockTransport → JSON verification."""
        model = _configure_pilot()
        captured_body = {}

        async def fake_upstream(request):
            import json
            captured_body["body"] = json.loads(request.read())
            return httpx.Response(200, json={
                "id": "chatcmpl-test", "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
            })

        transport = httpx.MockTransport(fake_upstream)
        from app.pilot import provider as prv
        original_call = prv.call_chat_completions

        async def patched_call(**kw):
            kw["transport"] = transport
            return await original_call(**kw)

        prv.call_chat_completions = patched_call
        try:
            resp = client.post(
                "/pilot",
                data={
                    "provider_key": "sk-real-key-12345abcdef",
                    "model_id": model,
                    "prompt": "hi",
                    "temperature": 0.2,
                    "max_tokens": 300,
                },
            )
        finally:
            prv.call_chat_completions = original_call

        assert resp.status_code == 200
        body = captured_body.get("body", {})
        assert isinstance(body.get("messages"), list)
        if body.get("messages"):
            msg = body["messages"][0]
            assert isinstance(msg, dict), f"message must be dict, got {type(msg)}"
            assert msg == {"role": "user", "content": "hi"}

    def test_serialize_chatmessage(self):
        """Direct test of _serialize_messages."""
        from app.pilot.provider import _serialize_messages
        from app.pilot.schemas import ChatMessage

        msgs = [ChatMessage(role="user", content="hello"), ChatMessage(role="assistant", content="world")]
        result = _serialize_messages(msgs)
        assert result == [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "world"}]

        result2 = _serialize_messages([{"role": "user", "content": "hi"}])
        assert result2 == [{"role": "user", "content": "hi"}]

        assert _serialize_messages([]) == []


# ---------------------------------------------------------------------------
# UI unconfigured POST test
# ---------------------------------------------------------------------------


class TestUIUnconfiguredPost:
    def test_post_when_not_configured_returns_200_with_error(self, client):
        """POST /pilot when pilot is not configured should return 200 with error, not 500."""
        resp = client.post("/pilot", data={"provider_key": "sk-test", "prompt": "hello"})
        assert resp.status_code == 200
        assert "pilot_not_configured" in resp.text
        assert "b14req_" in resp.text
        assert "NameError" not in resp.text
        assert resp.status_code != 500


class TestCleanInstall:
    def test_httpx_in_runtime_deps(self):
        """Verify httpx is a main dependency, not just dev."""
        import tomllib
        import os
        here = os.path.dirname(__file__)
        pyproject = os.path.join(here, "..", "pyproject.toml")
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
        deps = data["project"]["dependencies"]
        assert any("httpx" in d for d in deps), "httpx must be in main dependencies"
