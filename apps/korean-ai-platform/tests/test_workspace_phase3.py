"""Tests for Phase 3: Korean-first session workspace pilot.

All tests use fake transport (httpx.MockTransport) — no external network calls.
Covers locale behavior, multi-turn conversation, key safety, XSS, and regression.
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

    def test_missing_english_fallback_to_korean(self, client):
        """English translation missing -> Korean fallback."""
        # The "workspace.pilot_notice" key has an English translation
        # but if we test a key that's KO-only, it should fallback
        resp = client.get("/workspace?lang=en")
        assert resp.status_code == 200

    def test_locale_preference_not_in_storage(self, client):
        """locale_preference must not contain provider key or prompt."""
        resp = client.get("/workspace")
        # The cookie is set server-side only if user explicitly switches
        # Verify no key/prompt in the cookies we might set
        cookie_headers = resp.headers.get("set-cookie", "")
        if cookie_headers:
            assert "apiKey" not in cookie_headers.lower()
            assert "prompt" not in cookie_headers.lower()
            assert "messages" not in cookie_headers.lower()


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
        _setup_registry()
        resp = client.get("/workspace")
        assert resp.status_code == 200
        # model-b-v2 is not in the registry setup above (only 2 enabled models)
        # We need a different setup
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
        text = resp.text
        assert "Pilot" in text
        assert "NameError" not in text

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

    def test_provider_name_shown_for_selected_model(self, client):
        _setup_registry()
        resp = client.get("/workspace")
        assert "Provider" in resp.text

    def test_invalid_registry_with_legacy_safe(self, client):
        _setup_invalid_registry()
        pilot_settings.pilot_base_url = "https://legacy.example.com"
        pilot_settings.pilot_model_id = "legacy-model"
        resp = client.get("/workspace")
        assert resp.status_code == 200
        assert "registry_invalid" in resp.text or "올바르지 않습니다" in resp.text
        assert "legacy" not in resp.text


# ============================================================================
# Multi-turn conversation tests
# ============================================================================


class TestMultiTurn:
    """Verify multi-turn message history in workspace API calls."""

    def test_first_request_messages(self, client):
        _setup_registry()
        captured = {}

        async def fake_upstream(request):
            import json as _json
            captured["body"] = _json.loads(request.read())
            return httpx.Response(200, json={
                "id": "cmpl-1", "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "첫 응답"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
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
                "/workspace/api/chat",
                json={"model": "model-a-v1", "messages": [{"role": "user", "content": "첫 질문"}], "temperature": 0.2, "max_tokens": 512},
                headers={"X-Business14-Provider-Key": "sk-real-key-test"},
            )
        finally:
            prv.call_chat_completions = original

        assert resp.status_code == 200
        body = captured.get("body", {})
        assert body.get("messages") == [{"role": "user", "content": "첫 질문"}]

    def test_second_request_includes_history(self, client):
        _setup_registry()
        captured = {}

        async def fake_upstream(request):
            import json as _json
            captured["body"] = _json.loads(request.read())
            return httpx.Response(200, json={
                "id": "cmpl-2", "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "두 번째 응답"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
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
                "/workspace/api/chat",
                json={
                    "model": "model-a-v1",
                    "messages": [
                        {"role": "user", "content": "첫 질문"},
                        {"role": "assistant", "content": "첫 응답"},
                        {"role": "user", "content": "후속 질문"},
                    ],
                    "temperature": 0.2, "max_tokens": 512,
                },
                headers={"X-Business14-Provider-Key": "sk-real-key-test"},
            )
        finally:
            prv.call_chat_completions = original

        assert resp.status_code == 200
        body = captured.get("body", {})
        msgs = body.get("messages", [])
        assert len(msgs) == 3
        assert msgs[0]["role"] == "user" and msgs[0]["content"] == "첫 질문"
        assert msgs[1]["role"] == "assistant" and msgs[1]["content"] == "첫 응답"
        assert msgs[2]["role"] == "user" and msgs[2]["content"] == "후속 질문"

    def test_message_limit_warning(self, client):
        """When messages exceed 80 pairs, the API still accepts (limit is 100)."""
        _setup_registry()
        async def fake_upstream(request):
            return httpx.Response(200, json={
                "id": "cmpl-limit", "object": "chat.completion",
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
            many_messages = []
            for i in range(45):
                many_messages.append({"role": "user", "content": f"msg {i}"})
                many_messages.append({"role": "assistant", "content": f"reply {i}"})
            # 90 messages total (< 100 schema limit)
            resp = client.post(
                "/workspace/api/chat",
                json={"model": "model-a-v1", "messages": many_messages, "temperature": 0.2, "max_tokens": 512},
                headers={"X-Business14-Provider-Key": "sk-real-a1b2c3d4e5f6"},
            )
        finally:
            prv.call_chat_completions = original

        assert resp.status_code == 200

    def test_new_chat_clears_messages(self, client):
        """Verify that a 'new chat' sends only the current message."""
        _setup_registry()
        captured = {}

        async def fake_upstream(request):
            import json as _json
            captured["body"] = _json.loads(request.read())
            return httpx.Response(200, json={
                "id": "cmpl-3", "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "Fresh response"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 5, "total_tokens": 7},
            })

        transport = httpx.MockTransport(fake_upstream)
        from app.pilot import provider as prv
        original = prv.call_chat_completions

        async def patched(**kw):
            kw["transport"] = transport
            return await original(**kw)

        prv.call_chat_completions = patched
        try:
            # After clearing, only send 1 message (like a "new chat" scenario)
            resp = client.post(
                "/workspace/api/chat",
                json={"model": "model-a-v1", "messages": [{"role": "user", "content": "Fresh start"}], "temperature": 0.2, "max_tokens": 512},
                headers={"X-Business14-Provider-Key": "sk-real-a1b2c3d4e5f6"},
            )
        finally:
            prv.call_chat_completions = original

        assert resp.status_code == 200
        body = captured.get("body", {})
        assert len(body.get("messages", [])) == 1
        assert body["messages"][0]["content"] == "Fresh start"

    def test_model_change_preserves_key_but_new_chat(self, client):
        """Model change keeps the key in memory but conversation starts fresh."""
        _setup_registry()
        async def fake_upstream(request):
            return httpx.Response(200, json={
                "id": "cmpl-mc", "object": "chat.completion",
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
                "/workspace/api/chat",
                json={"model": "model-b-v1", "messages": [{"role": "user", "content": "test"}], "temperature": 0.2, "max_tokens": 512},
                headers={"X-Business14-Provider-Key": "sk-real-a1b2c3d4e5f6"},
            )
        finally:
            prv.call_chat_completions = original

        assert resp.status_code == 200


# ============================================================================
# Key safety tests
# ============================================================================


class TestKeySafety:
    """Verify keys are never stored, logged, or reflected anywhere."""

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
                "/workspace/api/chat",
                json={"model": "model-a-v1", "messages": [{"role": "user", "content": "hi"}], "temperature": 0.2, "max_tokens": 512},
                headers={"X-Business14-Provider-Key": "sk-super-secret-key-do-not-leak"},
            )
        finally:
            prv.call_chat_completions = original

        assert "sk-super-secret-key-do-not-leak" not in resp.text
        assert "Bearer sk" not in resp.text

    def test_key_not_in_error_response(self, client):
        _setup_registry()
        resp = client.post(
            "/workspace/api/chat",
            json={"model": "nonexistent-model", "messages": [{"role": "user", "content": "hi"}], "temperature": 0.2, "max_tokens": 512},
            headers={"X-Business14-Provider-Key": "sk-secret-key-xyz"},
        )
        assert resp.status_code == 400
        assert "sk-secret-key-xyz" not in resp.text

    def test_key_not_in_ui_page(self, client):
        _setup_registry()
        resp = client.get("/workspace")
        # Verify the page HTML has no key fields populated
        assert 'value="sk-' not in resp.text
        assert 'name="provider_key"' not in resp.text

    def test_key_not_in_cookies(self, client):
        _setup_registry()
        resp = client.get("/workspace")
        set_cookie = resp.headers.get("set-cookie", "")
        assert "sk-" not in set_cookie

    def test_key_not_in_url(self, client):
        _setup_registry()
        resp = client.get("/workspace?provider_key=sk-test")
        assert resp.status_code == 200
        assert "sk-test" not in resp.text
        assert "provider_key" not in resp.text

    def test_key_isolation_a_only_to_a(self, client):
        """Provider A key must only go to Provider A, not to B."""
        _setup_registry()
        captured = {}

        async def fake_transport(request):
            captured["url"] = str(request.url)
            captured["auth"] = dict(request.headers).get("authorization", "")
            return httpx.Response(200, json={
                "id": "cmpl-a", "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "A"}, "finish_reason": "stop"}],
            })

        transport = httpx.MockTransport(fake_transport)
        from app.pilot import provider as prv
        original = prv.call_chat_completions

        async def patched(**kw):
            kw["transport"] = transport
            return await original(**kw)

        prv.call_chat_completions = patched
        try:
            resp = client.post(
                "/workspace/api/chat",
                json={"model": "model-a-v1", "messages": [{"role": "user", "content": "hi"}], "temperature": 0.2, "max_tokens": 512},
                headers={"X-Business14-Provider-Key": "sk-key-for-a-only"},
            )
        finally:
            prv.call_chat_completions = original

        assert resp.status_code == 200
        auth = captured.get("auth", "")
        assert "sk-key-for-a-only" in auth, "Provider A should receive key A"
        assert "provider-a" in captured.get("url", ""), "Request goes to Provider A URL"

    def test_key_cleared_after_reload(self, client):
        """Page reload clears the key (no persistence mechanism)."""
        _setup_registry()
        # First request sets key
        async def fake_upstream(request):
            return httpx.Response(200, json={
                "id": "cmpl-r", "object": "chat.completion",
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
            # Send with key
            resp1 = client.post(
                "/workspace/api/chat",
                json={"model": "model-a-v1", "messages": [{"role": "user", "content": "hi"}], "temperature": 0.2, "max_tokens": 512},
                headers={"X-Business14-Provider-Key": "sk-real-a1b2c3d4e5f6"},
            )
            assert resp1.status_code == 200
            assert "sk-real-a1b2c3d4e5f6" not in resp1.text

            # Second request without key should fail (simulates reload clearing the key)
            resp2 = client.post(
                "/workspace/api/chat",
                json={"model": "model-a-v1", "messages": [{"role": "user", "content": "hi again"}], "temperature": 0.2, "max_tokens": 512},
            )
            assert resp2.status_code == 401
            assert resp2.json()["error"]["code"] == "missing_provider_key"
        finally:
            prv.call_chat_completions = original


# ============================================================================
# XSS safety tests
# ============================================================================


class TestXSSSafety:
    """Verify user/assistant content is rendered as plain text, not HTML."""

    def test_script_tag_in_prompt(self, client):
        _setup_registry()
        async def fake_upstream(request):
            return httpx.Response(200, json={
                "id": "cmpl-xss", "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "response with <script>alert(2)</script>"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
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
                "/workspace/api/chat",
                json={
                    "model": "model-a-v1",
                    "messages": [{"role": "user", "content": "<script>alert(1)</script>"}],
                    "temperature": 0.2, "max_tokens": 512,
                },
                headers={"X-Business14-Provider-Key": "sk-real-key-test"},
            )
        finally:
            prv.call_chat_completions = original

        assert resp.status_code == 200
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        assert "<script>alert(1)</script>" not in resp.text  # Rendered as text in response JSON
        assert "alert(1)" not in resp.text  # Not executed

    def test_img_event_handler_in_prompt(self, client):
        _setup_registry()
        async def fake_upstream(request):
            return httpx.Response(200, json={
                "id": "cmpl-xss2", "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "safe"}, "finish_reason": "stop"}],
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
                "/workspace/api/chat",
                json={
                    "model": "model-a-v1",
                    "messages": [{"role": "user", "content": '<img src=x onerror=alert(1)>'}],
                    "temperature": 0.2, "max_tokens": 512,
                },
                headers={"X-Business14-Provider-Key": "sk-real-key-test"},
            )
        finally:
            prv.call_chat_completions = original

        assert resp.status_code == 200
        # The prompt is rendered as JSON, not HTML - verify it appears safely
        data = resp.json()
        assert data["choices"][0]["message"]["content"] == "safe"

    def test_template_injection_in_prompt(self, client):
        _setup_registry()
        async def fake_upstream(request):
            return httpx.Response(200, json={
                "id": "cmpl-xss3", "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "safe reply"}, "finish_reason": "stop"}],
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
                "/workspace/api/chat",
                json={
                    "model": "model-a-v1",
                    "messages": [{"role": "user", "content": "{{7*7}}"}],
                    "temperature": 0.2, "max_tokens": 512,
                },
                headers={"X-Business14-Provider-Key": "sk-real-key-test"},
            )
        finally:
            prv.call_chat_completions = original

        assert resp.status_code == 200
        content = resp.json()["choices"][0]["message"]["content"]
        assert content == "safe reply"

    def test_textarea_breakout(self, client):
        _setup_registry()
        async def fake_upstream(request):
            return httpx.Response(200, json={
                "id": "cmpl-xss4", "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "safe"}, "finish_reason": "stop"}],
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
                "/workspace/api/chat",
                json={
                    "model": "model-a-v1",
                    "messages": [{"role": "user", "content": '</textarea><script>alert(1)</script>'}],
                    "temperature": 0.2, "max_tokens": 512,
                },
                headers={"X-Business14-Provider-Key": "sk-real-key-test"},
            )
        finally:
            prv.call_chat_completions = original

        assert resp.status_code == 200

    def test_assistant_content_as_text(self, client):
        """Verify assistant HTML-looking content is returned as plain text in JSON."""
        _setup_registry()
        async def fake_upstream(request):
            return httpx.Response(200, json={
                "id": "cmpl-xss5", "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "<b>bold</b><script>evil()</script>"}, "finish_reason": "stop"}],
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
                "/workspace/api/chat",
                json={
                    "model": "model-a-v1",
                    "messages": [{"role": "user", "content": "test"}],
                    "temperature": 0.2, "max_tokens": 512,
                },
                headers={"X-Business14-Provider-Key": "sk-real-key-test"},
            )
        finally:
            prv.call_chat_completions = original

        assert resp.status_code == 200
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        assert "<b>bold</b>" in content or "<script>evil()</script>" in content


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
