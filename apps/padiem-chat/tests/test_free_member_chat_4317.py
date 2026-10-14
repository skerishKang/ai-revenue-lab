"""Owner-approved Free baseline uses the existing Gemini 3.1 route for members.

This deliberately does not activate Plus/Pro/Max, mutate central membership,
or authorize a browser-supplied arbitrary exact model.
"""
from __future__ import annotations

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.main import create_app
from app.model_policy import FREE_B14_MODEL_ID, model_policy_is_executable, resolve_tier_policy
from test_auth_history import MemoryHistoryStore, add_test_user


@pytest.mark.asyncio
async def test_free_requires_membership_login_not_paid_upgrade() -> None:
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

    # Actual B14 mode without a login must reject BEFORE any provider POST.
    # Only the authentication decision is under test, no upstream mock response
    # or live model dispatch is ever allowed here.
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
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=live_app), base_url="https://chat.example.test",
    ) as client:
        denied = await client.post("/api/chat/stream", json=payload)
        assert denied.status_code == 401
        assert denied.json()["error"]["code"] == "unauthorized"
        denied_complete = await client.post("/api/chat", json=payload)
        assert denied_complete.status_code == 401
    assert resolve_tier_policy(payload["messages"], "free").model_id == FREE_B14_MODEL_ID


def test_no_browser_model_override_and_plus_hold_independent() -> None:
    free = resolve_tier_policy([{"role": "user", "content": "hello"}], "free")
    assert free.model_id == "google/gemini-3.1-flash-lite"
    assert free.profile == "free"
    assert not model_policy_is_executable("google/gemini-3.5-flash-lite")
