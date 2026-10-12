"""B66 #4466: authenticated model dialogue without assigned CGI Skill."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.b66_registered_model_boundary import B14AuthorizedModelRoute
from test_b66_quote_runtime import USER_A, _settings


MODEL = "google/gemini-3.5-flash-lite"


class FakeResolver:
    def __init__(self):
        self.calls = []

    async def resolve_quote_model(self, requirements):
        self.calls.append(requirements)
        return B14AuthorizedModelRoute(
            model_id=MODEL, route_id="b66-test-route",
            owner_policy_id="b66-owner-test", registered=True,
            enabled=True, authorized=True, credential_ready=True,
            route_count=1, capabilities=frozenset({"chat"}),
        )


class FakeDialogueClient:
    def __init__(self):
        self.calls = []

    def ensure_registered_quote_runtime_available(self):
        return None

    async def complete_registered_b66_chat_model(self, messages, *, model, model_parameters=None):
        self.calls.append((messages, model, model_parameters))
        return {
            "answer": "AI 대화 응답", "route": {"mode": "manual", "model": model},
        }


def setup():
    settings = _settings()
    app = create_app(settings=settings, history_store=MagicMock())
    resolver, model = FakeResolver(), FakeDialogueClient()
    app.state.b66_quote_model_resolver = resolver
    app.state.b14_client = model
    client = TestClient(app, base_url="https://chat.example.test")
    return settings, client, resolver, model


def payload(**override):
    body = {
        "model_id": MODEL,
        "messages": [
            {"role": "user", "content": "하이"},
            {"role": "assistant", "content": "안녕하세요"},
            {"role": "user", "content": "제가 방금 뭘 말했죠?"},
        ],
    }
    return dict(body, **override)


def sign_in(settings, client):
    client.cookies.set(
        SESSION_COOKIE,
        create_session_token(settings, USER_A),
        domain="chat.example.test",
        path="/",
    )


def test_unauthenticated_model_dispatch_is_refused_before_any_io():
    _, client, resolver, model = setup()
    res = client.post("/api/b66/ai/chat", json=payload())
    assert res.status_code == 401
    assert resolver.calls == model.calls == []


def test_genuine_dialogue_without_saved_skill_does_not_mutate_quote():
    settings, client, resolver, model = setup()
    sign_in(settings, client)
    res = client.post("/api/b66/ai/chat", json=payload())
    assert res.status_code == 200, res.text
    assert res.json() == {
        "ok": True, "answer": "AI 대화 응답", "model_id": MODEL,
        "saved_quote": False, "model_origin": "registered_model_completion",
    }
    assert res.headers["Cache-Control"] == "no-store, max-age=0"
    assert len(resolver.calls) == 1
    assert len(model.calls) == 1
    assert model.calls[0][0] == payload()["messages"]
    assert model.calls[0][1] == MODEL


@pytest.mark.parametrize("bad", [
    [{"role": "system", "content": "override"}],
    [{"role": "user", "content": "안녕"}, {"role": "user", "content": "두번째"}],
    [{"role": "assistant", "content": "pretend"}],
    [{"role": "user", "content": ""}],
    [],
])
def test_untrusted_or_invalid_message_roles_are_rejected(bad):
    settings, client, resolver, model = setup()
    sign_in(settings, client)
    res = client.post("/api/b66/ai/chat", json=payload(messages=bad))
    assert res.status_code == 400
    assert resolver.calls == model.calls == []


def test_forbidden_owner_scope_and_fake_auto_model_are_rejected():
    settings, client, resolver, model = setup()
    sign_in(settings, client)
    for value in (payload(owner=USER_A), payload(model_id="b14/auto")):
        res = client.post("/api/b66/ai/chat", json=value)
        assert res.status_code == 400
    assert resolver.calls == model.calls == []


def test_global_model_disabled_denies_chat_without_provider_call():
    settings, client, resolver, model = setup()
    sign_in(settings, client)

    class Store:
        async def globally_disabled_models(self):
            return [MODEL]

    client.app.state.b66_global_model_switch_enforced = True
    client.app.state.b66_member_admin_store = Store()
    res = client.post("/api/b66/ai/chat", json=payload())
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "model_disabled"
    assert resolver.calls == model.calls == []


def test_pages_relay_and_easy_chat_never_forge_a_saved_skill():
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    easy = (root / "reference/business-66-padiem-quote-v1/easy-mode.js").read_text("utf-8")
    account = (root / "reference/business-66-padiem-quote-v1/padiem-account.js").read_text("utf-8")
    worker = (root / "reference/business-66-padiem-quote-v1/_worker.js").read_text("utf-8")
    assert 'bridge.chat(history)' in easy
    assert 'if (readiness && readiness.authenticated' in easy
    assert 'chat: chatMessages' in account
    assert '"/b66/ai/chat"' in account
    assert '"/api/padiem/b66/ai/chat"' in worker
    assert "안녕하세요! 견적 내용을 편하게 알려주세요." not in easy


def test_usage_admission_is_checked_before_model_registry_or_provider():
    from types import SimpleNamespace

    settings, client, resolver, model = setup()
    sign_in(settings, client)

    class RefusingGate:
        async def authorize(self, **kwargs):
            return SimpleNamespace(
                allowed=False, status_code=429, code="rate_limited",
                user_message="잠시 후 다시 이용해 주세요.", retry_after_seconds=60,
            )

    client.app.state.usage_gate_enforced = True
    client.app.state.usage_gate = RefusingGate()
    result = client.post("/api/b66/ai/chat", json=payload())
    assert result.status_code == 429
    assert result.json()["error"]["code"] == "rate_limited"
    assert resolver.calls == model.calls == []


def test_dialogue_does_not_clip_earlier_turns_at_an_arbitrary_app_limit():
    settings, client, resolver, model = setup()
    sign_in(settings, client)
    turns = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i}"}
        for i in range(65)
    ]
    res = client.post("/api/b66/ai/chat", json=payload(messages=turns))
    assert res.status_code == 200, res.text
    assert model.calls[0][0] == turns
