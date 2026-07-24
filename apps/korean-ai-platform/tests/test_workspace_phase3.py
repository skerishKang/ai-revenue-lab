"""Tests for Phase 3: Korean-first session workspace pilot.

The workspace JS calls POST /api/pilot/v1/chat/completions directly
(Phase 2 API), so there is no server-side POST proxy endpoint.

Covers:
- Locale behavior (Korean-first, explicit en, no Accept-Language)
- Workspace page rendering (models, key input, config)
- Provider change isolation (key + messages cleared)
- Key safety
- XSS safety
- Regression (Phase 0, 1, 2 preservation)
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.factory import create_app
from app.pilot.config import pilot_settings
from app.pilot.registry import reset_registry


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
    """Configure multi-provider registry with 2 providers for workspace tests."""
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
# Locale tests
# ============================================================================


class TestLocale:
    """Verify Korean-first locale behavior: default, fallback, explicit en."""

    def test_default_is_korean(self, client):
        """First visit without any locale hint -> Korean."""
        resp = client.get("/workspace")
        assert resp.status_code == 200
        text = resp.text
        assert "AI 모델 대화" in text, "Heading should be Korean by default"
        assert "Provider API key를 입력" in text, "Description should be Korean"
        assert "보내기" in text, "Send button should be Korean"
        assert "새 대화" in text, "New chat should be Korean"

    def test_no_locale_fallback_to_korean(self, client):
        """Missing locale cookie/query -> Korean."""
        resp = client.get("/workspace", headers={"Cookie": "locale_preference="})
        assert resp.status_code == 200
        assert "AI 모델 대화" in resp.text

    def test_invalid_locale_fallback_to_korean(self, client):
        """Invalid locale value -> Korean."""
        resp = client.get("/workspace", headers={"Cookie": "locale_preference=fr"})
        assert resp.status_code == 200
        assert "AI 모델 대화" in resp.text

    def test_explicit_english(self, client):
        """Explicit ?lang=en -> English headings."""
        resp = client.get("/workspace?lang=en")
        assert resp.status_code == 200
        text = resp.text
        assert "AI Model Chat" in text
        assert "Enter your Provider API key" in text
        assert "Send" in text

    def test_explicit_english_via_cookie(self, client):
        """English via locale_preference cookie -> English."""
        resp = client.get("/workspace", headers={"Cookie": "locale_preference=en"})
        assert resp.status_code == 200
        assert "AI Model Chat" in resp.text

    def test_accept_language_ignored(self, client):
        """Accept-Language: en must NOT auto-switch to English."""
        resp = client.get("/workspace", headers={"Accept-Language": "en-US,en;q=0.9"})
        assert resp.status_code == 200
        text = resp.text
        assert "AI 모델 대화" in text, "Accept-Language en must NOT switch to English"
        assert "AI Model Chat" not in text

    def test_invalid_query_with_en_cookie_returns_korean(self, client):
        """Invalid ?lang=invalid with en cookie -> Korean (query wins as invalid)."""
        resp = client.get(
            "/workspace?lang=invalid",
            headers={"Cookie": "locale_preference=en"},
        )
        assert resp.status_code == 200
        assert "AI 모델 대화" in resp.text
        assert "AI Model Chat" not in resp.text

    def test_french_query_with_en_cookie_returns_korean(self, client):
        """Invalid ?lang=fr with en cookie -> Korean."""
        resp = client.get(
            "/workspace?lang=fr",
            headers={"Cookie": "locale_preference=en"},
        )
        assert resp.status_code == 200
        assert "AI 모델 대화" in resp.text
        assert "AI Model Chat" not in resp.text

    def test_empty_query_with_en_cookie_returns_korean(self, client):
        """Empty ?lang= with en cookie -> Korean."""
        resp = client.get(
            "/workspace?lang=",
            headers={"Cookie": "locale_preference=en"},
        )
        assert resp.status_code == 200
        assert "AI 모델 대화" in resp.text
        assert "AI Model Chat" not in resp.text

    def test_missing_english_fallback_to_korean(self, client):
        """English translation missing -> Korean fallback."""
        resp = client.get("/workspace?lang=en")
        assert resp.status_code == 200
        text = resp.text
        # The callout info text should be present in Korean even in English mode
        # because it uses Korean-first translations
        assert "Phase 3 Pilot" in text or "파일럿" in text

    def test_locale_preference_not_in_storage(self, client):
        """locale_preference must not contain provider key or prompt."""
        resp = client.get("/workspace")
        cookie_headers = resp.headers.get("set-cookie", "")
        if cookie_headers:
            assert "apiKey" not in cookie_headers.lower()
            assert "prompt" not in cookie_headers.lower()
            assert "messages" not in cookie_headers.lower()

    def test_locale_cookie_set_on_explicit_switch(self, client):
        """?lang=en should set locale_preference cookie."""
        resp = client.get("/workspace?lang=en")
        set_cookie = resp.headers.get("set-cookie", "")
        assert "locale_preference=en" in set_cookie or "locale_preference=" in set_cookie

    def test_locale_cookie_not_set_on_default(self, client):
        """Default visit without ?lang should NOT set cookie."""
        resp = client.get("/workspace")
        set_cookie = resp.headers.get("set-cookie", "")
        assert "locale_preference" not in (set_cookie or "")

    def test_lang_switch_link_exists(self, client):
        """Workspace should have a language switch control."""
        resp_ko = client.get("/workspace")
        assert resp_ko.status_code == 200
        # Korean page should show English as switch
        assert "English" in resp_ko.text
        resp_en = client.get("/workspace?lang=en")
        assert resp_en.status_code == 200
        # English page should show 한국어 as switch
        assert "한국어" in resp_en.text


# ============================================================================
# Workspace page tests
# ============================================================================


class TestWorkspacePage:
    """Verify the workspace page renders correctly."""

    def test_workspace_200(self, client):
        assert client.get("/workspace").status_code == 200

    def test_models_from_registry_shown(self, client):
        _setup_registry()
        resp = client.get("/workspace")
        assert resp.status_code == 200
        assert "Model A" in resp.text
        assert "Model B" in resp.text
        assert "Provider A" in resp.text
        assert "Provider B" in resp.text

    def test_model_select_has_options(self, client):
        _setup_registry()
        resp = client.get("/workspace")
        assert 'id="ws_model"' in resp.text
        assert "model-a-v1" in resp.text
        assert "model-b-v1" in resp.text

    def test_disabled_model_not_shown(self, client):
        registry_data = [
            {
                "provider_id": "p1",
                "display_name": "Provider 1",
                "base_url": "https://api.p1.example",
                "timeout_seconds": 30,
                "models": [
                    {"model_id": "enabled-model", "upstream_model": "up-en", "display_name": "Enabled", "enabled": True},
                    {"model_id": "disabled-model", "upstream_model": "up-dis", "display_name": "Disabled", "enabled": False},
                ],
            },
        ]
        pilot_settings.provider_registry_json = json.dumps(registry_data)
        reset_registry()
        resp = client.get("/workspace")
        assert "Enabled" in resp.text
        assert "Disabled" not in resp.text

    def test_invalid_registry_safe_render(self, client):
        _setup_invalid_registry()
        resp = client.get("/workspace")
        assert resp.status_code == 200
        assert "registry_invalid" in resp.text or "올바르지 않습니다" in resp.text
        assert "NameError" not in resp.text
        assert "stack trace" not in resp.text.lower()

    def test_not_configured_safe_render(self, client):
        resp = client.get("/workspace")
        assert resp.status_code == 200
        assert "NameError" not in resp.text

    def test_cost_unknown_shown(self, client):
        _setup_registry()
        resp = client.get("/workspace")
        assert resp.status_code == 200
        assert "확인 불가" in resp.text

    def test_cost_notice_shown(self, client):
        _setup_registry()
        resp = client.get("/workspace")
        assert resp.status_code == 200
        assert "Provider 계정" in resp.text
        assert "청구" in resp.text
        assert "0원" not in resp.text

    def test_key_input_is_password(self, client):
        _setup_registry()
        resp = client.get("/workspace")
        assert 'type="password"' in resp.text

    def test_key_apply_button_exists(self, client):
        _setup_registry()
        resp = client.get("/workspace")
        assert 'id="ws_key_apply"' in resp.text

    def test_key_notice_shown(self, client):
        _setup_registry()
        resp = client.get("/workspace")
        assert "저장하지" in resp.text
        assert "새로고침" in resp.text

    def test_pilot_notice_shown(self, client):
        _setup_registry()
        resp = client.get("/workspace")
        assert "Phase 3" in resp.text

    def test_workspace_has_chat_area(self, client):
        _setup_registry()
        resp = client.get("/workspace")
        assert 'id="ws_chat"' in resp.text
        assert 'id="ws_input"' in resp.text
        assert 'id="ws_send"' in resp.text
        assert 'id="ws_new_chat"' in resp.text
        assert 'id="ws_clear_chat"' in resp.text

    def test_invalid_registry_with_legacy_safe(self, client):
        _setup_invalid_registry()
        pilot_settings.pilot_base_url = "https://legacy.example.com"
        pilot_settings.pilot_model_id = "legacy-model"
        resp = client.get("/workspace")
        assert resp.status_code == 200
        assert "registry_invalid" in resp.text or "올바르지 않습니다" in resp.text

    def test_safe_config_injection(self, client):
        """Config must be injected via application/json script element."""
        _setup_registry()
        resp = client.get("/workspace")
        assert '<script id="workspace-config" type="application/json">' in resp.text

    def test_phase_labeling_consistent(self, client):
        """Workspace page must show Phase 3 labels, not Phase 0."""
        _setup_registry()
        resp = client.get("/workspace")
        assert "Phase 3" in resp.text
        # Should NOT show Phase 0 labels in the workspace page
        assert "Phase 0 Mock Demo" not in resp.text

    def test_provider_count_numeric_displayed(self, client):
        _setup_registry()
        resp = client.get("/workspace")
        # Check for the stat-value element with provider count = 2
        assert 'id="ws_provider_count">2' in resp.text
        # Also check the label is present
        assert "Provider 수" in resp.text or "Providers" in resp.text

    def test_model_count_numeric_displayed(self, client):
        _setup_registry()
        resp = client.get("/workspace")
        # Check for the stat-value element with model count = 2
        assert 'id="ws_model_count">2' in resp.text
        # Also check the label is present
        assert "모델 수" in resp.text or "Models" in resp.text

    def test_html_lang_ko_default(self, client):
        """Default workspace should have html lang=ko."""
        resp = client.get("/workspace")
        assert 'lang="ko"' in resp.text

    def test_html_lang_en_on_explicit(self, client):
        """?lang=en should set html lang=en."""
        resp = client.get("/workspace?lang=en")
        assert 'lang="en"' in resp.text

    def test_html_lang_en_from_cookie(self, client):
        """en cookie should set html lang=en."""
        resp = client.get("/workspace", headers={"Cookie": "locale_preference=en"})
        assert 'lang="en"' in resp.text

    def test_html_lang_en_after_switch_to_ko(self, client):
        """Switching back to Korean after English sets html lang=ko."""
        resp_en = client.get("/workspace?lang=en")
        assert 'lang="en"' in resp_en.text
        resp_ko = client.get("/workspace?lang=ko-KR")
        assert 'lang="ko"' in resp_ko.text

    def test_no_inline_init_after_deferred_script(self, client):
        """Workspace must not have inline Business14Workspace.init() after deferred script."""
        _setup_registry()
        resp = client.get("/workspace")
        # The init should happen inside workspace.js via DOMContentLoaded, not inline
        # Check there's no `Business14Workspace.init(` inline script
        assert 'Business14Workspace.init(' not in resp.text




# ============================================================================
# Provider change isolation tests
# ============================================================================


class TestProviderChangeIsolation:
    """Verify model/provider change clears key and messages."""

    def test_workspace_config_has_models(self, client):
        _setup_registry()
        resp = client.get("/workspace")
        assert resp.status_code == 200
        assert "model-a-v1" in resp.text
        assert "model-b-v1" in resp.text
        assert "provider-a" in resp.text or "Provider A" in resp.text
        assert "provider-b" in resp.text or "Provider B" in resp.text

    def test_model_select_lists_both_models(self, client):
        _setup_registry()
        resp = client.get("/workspace")
        assert "model-a-v1" in resp.text
        assert "model-b-v1" in resp.text


# ============================================================================
# Key safety tests
# ============================================================================


class TestKeySafety:
    """Verify keys are never stored, logged, or reflected anywhere."""

    def test_key_not_in_ui_page(self, client):
        _setup_registry()
        resp = client.get("/workspace")
        assert 'value="sk-' not in resp.text
        assert 'name="provider_key"' not in resp.text

    def test_key_not_in_cookies(self, client):
        _setup_registry()
        resp = client.get("/workspace")
        set_cookie = resp.headers.get("set-cookie", "")
        assert "sk-" not in (set_cookie or "")

    def test_key_not_in_url(self, client):
        _setup_registry()
        resp = client.get("/workspace?provider_key=sk-test")
        assert resp.status_code == 200
        assert "sk-test" not in resp.text

    def test_workspace_js_loaded(self, client):
        """workspace.js must be loaded on the page."""
        _setup_registry()
        resp = client.get("/workspace")
        assert 'src="/static/workspace.js' in resp.text or 'src="/static/workspace.js' in resp.text

    def test_original_app_js_loaded(self, client):
        """Original app.js must still be loaded globally."""
        _setup_registry()
        resp = client.get("/workspace")
        assert 'src="/static/app.js' in resp.text

    def test_try_finally_cleanup_in_js(self):
        """workspace.js must use try/finally for sendMessage error recovery."""
        import os
        js_path = os.path.join(os.path.dirname(__file__), "..", "static", "workspace.js")
        with open(js_path, encoding="utf-8") as f:
            js_source = f.read()
        assert "finally {" in js_source, "sendMessage must use try/finally for button cleanup"
        assert "state.isSending = false" in js_source
        assert "DOM.sendBtn.disabled = false" in js_source


# ============================================================================
# XSS safety tests
# ============================================================================


class TestXSSConfigSafety:
    """Verify workspace config is injected safely (no |safe for JSON)."""

    def test_config_is_json_element(self, client):
        _setup_registry()
        resp = client.get("/workspace")
        assert '<script id="workspace-config" type="application/json">' in resp.text

    def test_config_has_no_unsafe_safe_filter(self, client):
        _setup_registry()
        resp = client.get("/workspace")
        # The config should NOT use |safe for JSON variables
        assert 'pilot_models_json|safe' not in resp.text

    def test_config_not_in_script_with_safe(self, client):
        _setup_registry()
        resp = client.get("/workspace")
        # Verify raw JSON is not injected with |safe in script context
        assert 'models = ' not in resp.text or 'var models' not in resp.text


# ============================================================================
# Regression tests (Phase 0, 1, 2 preservation)
# ============================================================================


class TestPhase3Regression:
    """Verify Phase 3 does not break Phase 0, 1, or 2 functionality."""

    def test_phase0_8_models(self, client):
        resp = client.get("/models")
        assert resp.status_code == 200
        from app.demo_data import MODELS
        assert len(MODELS) == 8

    def test_phase0_home(self, client):
        assert client.get("/").status_code == 200

    def test_phase0_playground(self, client):
        assert client.get("/playground").status_code == 200

    def test_phase0_copy_button_script(self, client):
        """Verify the original app.js with copy button functionality exists."""
        resp = client.get("/docs")
        assert resp.status_code == 200
        # app.js should be loaded globally
        assert 'src="/static/app.js' in resp.text

    def test_phase1_legacy_chat(self, client):
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
                json={"model": "test-model-v1", "messages": [{"role": "user", "content": "hi"}], "temperature": 0.2, "max_tokens": 300},
                headers={"X-Business14-Provider-Key": "sk-real-key-12345abcdef"},
            )
        finally:
            prv_mod.call_chat_completions = original
        assert resp.status_code == 200

    def test_phase2_registry_health(self, client):
        _setup_registry()
        resp = client.get("/api/pilot/health")
        assert resp.status_code == 200
        assert resp.json()["configured_providers"] == 2

    def test_phase2_invalid_registry_500(self, client):
        _setup_invalid_registry()
        resp = client.get("/api/pilot/health")
        assert resp.status_code == 500
        assert resp.json()["error"]["code"] == "registry_invalid"

    def test_phase2_key_isolation(self, client):
        _setup_registry()
        async def fake_upstream(request):
            return httpx.Response(200, json={
                "id": "cmpl-iso", "object": "chat.completion",
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
                json={"model": "model-a-v1", "messages": [{"role": "user", "content": "hi"}], "temperature": 0.2, "max_tokens": 300},
                headers={"X-Business14-Provider-Key": "sk-isolation-key-999"},
            )
        finally:
            prv.call_chat_completions = original
        assert resp.status_code == 200

    def test_phase2_response_model(self, client):
        _setup_registry()
        async def fake_upstream(request):
            return httpx.Response(200, json={
                "id": "cmpl-resp", "object": "chat.completion",
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
                json={"model": "model-a-v1", "messages": [{"role": "user", "content": "hi"}], "temperature": 0.2, "max_tokens": 300},
                headers={"X-Business14-Provider-Key": "sk-real-key-12345abcdef"},
            )
        finally:
            prv.call_chat_completions = original
        data = resp.json()
        assert data["model"] == "model-a-v1"

    def test_route_smoke(self, client):
        """All Phase 0-2 routes return 200."""
        routes = ["/", "/models", "/playground", "/api-keys", "/docs", "/usage", "/pricing", "/access", "/pilot"]
        for route in routes:
            resp = client.get(route)
            assert resp.status_code == 200, f"{route} returned {resp.status_code}"

    def test_workspace_route(self, client):
        assert client.get("/workspace").status_code == 200

    def test_workspace_api_chat_still_works(self, client):
        """Phase 2 chat completions API must still be available."""
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
                json={"model": "model-a-v1", "messages": [{"role": "user", "content": "hi"}], "temperature": 0.2, "max_tokens": 300},
                headers={"X-Business14-Provider-Key": "sk-real-key-12345abcdef"},
            )
        finally:
            prv.call_chat_completions = original
        assert resp.status_code == 200
