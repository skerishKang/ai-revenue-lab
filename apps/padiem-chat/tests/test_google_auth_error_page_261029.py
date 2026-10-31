"""#6114 — login failures speak the owner's language, and a no-answer never
means signed-out.

The Google callback used to hand a browser navigation the raw JSON envelope
(``{"error":{"code":"invalid_oauth_state",...}}``). A navigation that asked for
text/html now gets one Korean screen with one button that starts the login over
with a fresh signed state; fetches keep their JSON contract untouched.

The OAuth state itself needed no rework: it is the HMAC-signed cookie (purpose
"padiem-chat/oauth-state/v1", ten-minute expiry, HttpOnly·Secure·SameSite=Lax,
constant-time compare) — isolate-independent by construction. These pins hold
that design so a future state store cannot quietly grow isolate memory.
"""
from __future__ import annotations

import httpx
import pytest

from app.android_auth_routes import _PAGE_STYLE  # the same page family the handoff uses
from app.app_factory import create_app
from app.auth import OAUTH_STATE_MAX_AGE_SECONDS, oauth_state_cookie_kwargs
from tests.test_auth_history import MemoryHistoryStore, google_settings

RETRY_HREF = "/auth/google/start"


def test_oauth_state_stays_a_signed_cookie_not_isolate_memory():
    # The state lives in an HMAC-signed cookie and dies with its ten-minute
    # expiry: no module global, no isolate memory, no D1 round-trip. A deploy
    # between the login's start and its callback cannot orphan it.
    assert OAUTH_STATE_MAX_AGE_SECONDS == 600
    kwargs = oauth_state_cookie_kwargs()
    assert kwargs["httponly"] is True
    assert kwargs["secure"] is True
    assert kwargs["samesite"] == "lax"
    assert kwargs["max_age"] == 600


@pytest.mark.asyncio
async def test_callback_navigation_gets_korean_screen_instead_of_raw_json():
    app = create_app(google_settings(), history_store=MemoryHistoryStore())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test"
    ) as client:
        response = await client.get(
            "/auth/google/callback?state=bad&code=code",
            headers={"Accept": "text/html,application/xhtml+xml"},
        )
    assert response.status_code == 400
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "로그인을 마치지 못했어요" in body
    assert "로그인 요청을 확인할 수 없습니다. 다시 로그인해 주세요." in body
    assert f'href="{RETRY_HREF}"' in body
    assert "다시 로그인" in body
    # The JSON envelope never reaches a navigation.
    assert "invalid_oauth_state" not in body
    # Same page family as the product's other auth pages, and never cached.
    assert _PAGE_STYLE in body


@pytest.mark.asyncio
async def test_callback_fetch_keeps_its_json_contract():
    app = create_app(google_settings(), history_store=MemoryHistoryStore())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test"
    ) as client:
        response = await client.get("/auth/google/callback?state=bad&code=code")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_oauth_state"


@pytest.mark.asyncio
async def test_unavailable_login_navigation_gets_the_same_screen():
    # auth_mode off: the login surface exists in the navigation path but the
    # backend cannot serve it — the owner still gets the screen, not JSON.
    app = create_app(google_settings(auth_mode="off"), history_store=MemoryHistoryStore())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test"
    ) as client:
        start = await client.get(
            "/auth/google/start", headers={"Accept": "text/html,application/xhtml+xml"}
        )
    assert start.status_code == 503
    assert "text/html" in start.headers["content-type"]
    assert "로그인을 현재 사용할 수 없습니다." in start.text
    assert f'href="{RETRY_HREF}"' in start.text


def test_the_browser_asks_once_more_before_it_presents_signed_out():
    # The status read that produced no answer (a Worker restart's 1101/1102)
    # gets exactly one silent re-ask in both status consumers; a definitive
    # guest answer is never retried.
    app_js = _read("app.js")
    assert "async function fetchAuthStatusOnce()" in app_js
    assert "for (let attempt = 0; attempt < 2; attempt += 1)" in app_js
    capabilities = _read("product-capabilities.js")
    assert "async function readAuthStatusWithRetry()" in capabilities
    assert "if (answer.ok) return answer;" in capabilities


def _read(name: str) -> str:
    from pathlib import Path

    return (Path(__file__).resolve().parents[1] / "static" / name).read_text(encoding="utf-8")
