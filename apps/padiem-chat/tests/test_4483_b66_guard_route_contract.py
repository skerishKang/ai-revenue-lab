"""#4483: the B66 dialogue route builds and applies the product-scoped guard.

The guard itself is exercised in ``test_4483_final_dispatch_guard``; this file
pins the route composition: a per-request guard is requested for the ``b66``
product with the authorized exact model, and it is applied to the same client
that performs the dispatch.  The fake client records the guard so the test also
proves the route never keeps it in shared app state.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from app import b66_ai_chat_routes
from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.b66_registered_model_boundary import B14AuthorizedModelRoute
from starlette.testclient import TestClient
from test_b66_quote_runtime import USER_A, _settings

MODEL = "google/gemini-3.5-flash-lite"


class FakeResolver:
    async def resolve_quote_model(self, requirements):
        return B14AuthorizedModelRoute(
            model_id=MODEL, route_id="b66-test-route",
            owner_policy_id="b66-owner-test", registered=True,
            enabled=True, authorized=True, credential_ready=True,
            route_count=1, capabilities=frozenset({"chat"}),
        )


class FakeDialogueClient:
    def __init__(self):
        self.calls = []
        self.guards = []

    def ensure_registered_quote_runtime_available(self):
        return None

    def with_guard(self, guard):
        self.guards.append(guard)
        return self

    async def complete_registered_b66_chat_model(
        self, messages, *, model, additional_system_context=None,
        model_parameters=None, **kwargs,
    ):
        self.calls.append(model)
        return {
            "answer": "AI 대화 응답", "route": {"mode": "manual", "model": model},
        }


def _setup():
    settings = _settings()
    app = create_app(settings=settings, history_store=MagicMock())
    app.state.b66_quote_model_resolver = FakeResolver()
    app.state.b14_client = FakeDialogueClient()
    client = TestClient(app, base_url="https://chat.example.test")
    client.cookies.set(
        SESSION_COOKIE,
        create_session_token(settings, USER_A),
        domain="chat.example.test",
        path="/",
    )
    return client, app.state.b14_client


def _payload():
    return {
        "model_id": MODEL,
        "messages": [
            {"role": "user", "content": "하이"},
            {"role": "assistant", "content": "안녕하세요"},
            {"role": "user", "content": "방금 뭐라고 했죠?"},
        ],
    }


def test_b66_route_requests_and_applies_the_product_scoped_guard(monkeypatch):
    client, model = _setup()
    sentinel = object()
    captured = []

    async def fake_create_guard(
        request, model_id, store, catalog, *,
        product_id, requested_tier,
    ):
        captured.append({
            "model_id": model_id,
            "store": store,
            "catalog": catalog,
            "product_id": product_id,
            "requested_tier": requested_tier,
        })
        return sentinel

    monkeypatch.setattr(
        b66_ai_chat_routes, "create_guard_from_request", fake_create_guard,
    )

    response = client.post("/api/b66/ai/chat", json=_payload())

    assert response.status_code == 200, response.text
    assert captured == [{
        "model_id": MODEL,
        "store": None,
        "catalog": None,
        "product_id": "b66",
        "requested_tier": None,
    }]
    assert model.guards == [sentinel]
    assert model.calls == [MODEL]


def test_b66_route_dispatch_is_unchanged_when_no_guard_is_available(monkeypatch):
    client, model = _setup()

    async def no_guard(*args, **kwargs):
        return None

    monkeypatch.setattr(b66_ai_chat_routes, "create_guard_from_request", no_guard)

    response = client.post("/api/b66/ai/chat", json=_payload())

    assert response.status_code == 200, response.text
    assert model.guards == []
    assert model.calls == [MODEL]
