"""Owner-approved Free baseline uses the existing Gemini 3.1 route for members.

This deliberately does not activate Plus/Pro/Max, mutate central membership,
or authorize a browser-supplied arbitrary exact model. #5474 (Owner decision
2026-10-24) keeps Free as the anonymous baseline too, bounded by the usage
gate; a paid upgrade is never inferred from the request.
"""
from __future__ import annotations

import httpx
import json
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.main import create_app
from app.model_policy import FREE_B14_MODEL_ID, model_policy_is_executable, resolve_tier_policy
from test_auth_history import MemoryHistoryStore, add_test_user


@pytest.mark.asyncio
async def test_anonymous_free_needs_no_paid_upgrade_and_stays_bounded() -> None:
    settings = Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="test-client.apps.googleusercontent.com",
        google_client_secret="test-only-not-a-credential",
        session_secret="test-free-member-route-secret-0000000000000000000",
    )
    store = MemoryHistoryStore()
    profile = await add_test_user(store)
    app = create_app(settings, history_store=store)
    payload = {"messages": [{"role": "user", "content": "current date"}], "mode": "auto", "tier": "free"}
    # Offline mock preview is deliberately anonymous and must not be blocked
    # by the production Free membership gate (no provider or key is present).
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test",
    ) as client:
        mock_public = await client.post("/api/chat", json=payload)
        assert mock_public.status_code == 200
        token = create_session_token(settings, profile.id)
        client.cookies.set(SESSION_COOKIE, token, domain="chat.example.test")
        allowed = await client.post("/api/chat", json=payload)
        assert allowed.status_code == 200, allowed.text

    # Actual B14 mode without a login is the anonymous Free lane since #5474
    # (Owner decision 2026-10-24). The usage gate answers before any provider
    # POST, and the request never buys a paid tier. Only the gating decision is
    # under test; no upstream mock response or live dispatch is allowed here.
    live_settings = Settings.from_values(
        runtime_mode="b14",
        b14_base_url="https://b14.test.invalid",
        auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="test-client.apps.googleusercontent.com",
        google_client_secret="test-only-not-a-credential",
        session_secret="test-free-member-route-secret-0000000000000000000",
    )
    live_app = create_app(live_settings, history_store=store)
    live_app.state.usage_gate_enforced = True
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=live_app), base_url="https://chat.example.test",
    ) as client:
        bounded = await client.post("/api/chat/stream", json=payload)
        assert bounded.status_code == 503
        assert bounded.json()["error"]["code"] == "live_abuse_gate_unavailable"
        bounded_complete = await client.post("/api/chat", json=payload)
        assert bounded_complete.status_code == 503
    assert resolve_tier_policy(payload["messages"], "free").model_id == FREE_B14_MODEL_ID


def test_free_selection_stays_independent_of_the_google_paid_primary() -> None:
    free = resolve_tier_policy([{"role": "user", "content": "hello"}], "free")
    assert free.model_id == FREE_B14_MODEL_ID
    assert free.profile == "free"
    assert model_policy_is_executable("google/gemini-3.5-flash-lite")
    # A paid executable route never replaces Free's requested grade or model.
    assert free.model_id != "google/gemini-3.5-flash-lite"

@pytest.mark.asyncio
async def test_signed_in_free_dispatches_exact_model_through_existing_b14_client() -> None:
    """No real provider or secrets. Proves the full Free API -> exact-model seam."""
    store = MemoryHistoryStore()
    profile = await add_test_user(store)
    settings = Settings.from_values(
        runtime_mode="b14",
        b14_base_url="https://b14.example.test",
        auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="test-client.apps.googleusercontent.com",
        google_client_secret="synthetic-only",
        session_secret="test-free-member-route-secret-0000000000000000000",
    )
    captured = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured.append(body)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "Hello from Free"}}],
                "business14": {
                    "request_id": "b14req_free_test",
                    "route_mode": "manual",
                    "selected_model": body["model"],
                    "selected_provider": "Google AI Studio",
                },
            },
        )

    app = create_app(
        settings,
        history_store=store,
        transport=httpx.MockTransport(handler),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test",
    ) as client:
        client.cookies.set(
            SESSION_COOKIE,
            create_session_token(settings, profile.id),
            domain="chat.example.test",
            path="/",
        )
        response = await client.post(
            "/api/chat",
            json={
                "messages": [{"role": "user", "content": "Please answer simply"}],
                "tier": "free",
                "mode": "auto",
            },
        )
    assert response.status_code == 200, response.text
    assert response.json()["answer"] == "Hello from Free"
    assert len(captured) == 1  # one dispatch only, no retries or fallback
    assert captured[0]["model"] == FREE_B14_MODEL_ID
