"""#7173 PR4 — the Util app's quote preview wrapper.

The Utill 탭's 견적서 초안 screen must not become an anonymous or executing
surface: the wrapper requires the same signed-in session the other Util tools
use, then delegates byte-for-byte to the existing deterministic manual-intake
preview. It never calls the execute lane, a model, or a usage bucket.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.main import create_app
from app.usage_gate import InMemoryUsageCounterStore
from app.util_quote_routes import UTIL_QUOTE_PREVIEW_PATH

BASE = "https://chat.example.test"
SESSION_SECRET = "phase-quote-preview-session-secret-not-real-000000"
OWNER = "usr_" + "b" * 32


def _settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url=BASE,
        google_client_id="phase-quote.apps.googleusercontent.com",
        google_client_secret="unit-secret",
        session_secret=SESSION_SECRET,
        web_provider="off",
    )


class _History:
    def __init__(self):
        self.users = {OWNER: SimpleNamespace(id=OWNER, email="owner@example.test")}

    async def get_user(self, user_id):
        return self.users.get(user_id)


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=BASE,
        follow_redirects=True, headers={"Origin": BASE},
    )


@pytest.mark.asyncio
async def test_the_wrapper_refuses_an_anonymous_preview() -> None:
    app = create_app(_settings(), history_store=_History())
    client = _client(app)
    try:
        response = await client.post(UTIL_QUOTE_PREVIEW_PATH,
                                     json={"content": "견적 요청", "channel": "kakao", "action": "quote"})
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthorized"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_a_signed_in_preview_delegates_the_existing_projection() -> None:
    store = InMemoryUsageCounterStore()
    settings = _settings()
    app = create_app(settings, history_store=_History(), usage_store=store)
    client = _client(app)
    client.cookies.set(SESSION_COOKIE, create_session_token(settings, OWNER),
                       domain="chat.example.test", path="/")
    try:
        response = await client.post(
            UTIL_QUOTE_PREVIEW_PATH,
            json={"content": "A상사에서 10박스 견적 요청", "channel": "kakao",
                  "action": "quote", "sender_hint": "A상사 담당자"},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["ok"] is True
        preview = data["preview"]
        assert isinstance(preview["result_text"], str) and preview["result_text"].strip()
        assert "견적서 초안" in preview["result_text"]
        assert isinstance(preview["title"], str) and preview["title"]
        # Deterministic preview: no model/usage bucket was touched.
        assert store.consume_calls == 0 and store.counts == {}
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_invalid_action_and_oversized_request_keep_the_preview_contract() -> None:
    settings = _settings()
    app = create_app(settings, history_store=_History())
    client = _client(app)
    client.cookies.set(SESSION_COOKIE, create_session_token(settings, OWNER),
                       domain="chat.example.test", path="/")
    try:
        invalid = await client.post(UTIL_QUOTE_PREVIEW_PATH,
                                    json={"content": "요청", "action": "bogus"})
        assert invalid.status_code == 400
        assert invalid.json()["error"]["code"] == "invalid_action"

        too_long = await client.post(UTIL_QUOTE_PREVIEW_PATH,
                                     json={"content": "가" * 13000, "action": "quote"})
        assert too_long.status_code == 400
        assert too_long.json()["error"]["code"] == "content_too_long"
    finally:
        await client.aclose()


def test_the_wrapper_only_delegates_and_never_executes() -> None:
    source = (Path(__file__).resolve().parents[1] / "app" / "util_quote_routes.py").read_text(
        encoding="utf-8"
    )
    assert "from .claw_routes import claw_manual_intake_preview" in source
    assert "return await claw_manual_intake_preview(request)" in source
    assert "ManualIntakeRouter(" not in source
    assert "manual-intake/execute" not in source
    assert UTIL_QUOTE_PREVIEW_PATH == "/api/util/quote/preview"
