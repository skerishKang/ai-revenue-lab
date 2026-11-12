"""#7552 — only the browser that completed Google may confirm an app sign-in.

The party that creates a handoff holds the claim secret, the displayed code
and the authorization URL (with its signed state). The confirmation form must
therefore not accept that party's own post: it is bound to the browser the
Google callback ran in.
"""
from __future__ import annotations

from urllib.parse import quote

import httpx
import pytest

from app.android_auth_routes import ANDROID_HANDOFF_SECRET_HEADER
from app.android_auth_store import (
    HANDOFF_STATUS_AWAITING_CONFIRMATION,
    HANDOFF_STATUS_READY,
    InMemoryAndroidAuthHandoffStore,
)
from app.auth import SESSION_COOKIE
from app.main import create_app
from test_android_auth_handoff import _google_transport
from test_auth_history import MemoryHistoryStore, google_settings

BASE_URL = "https://chat.example.test"
ANDROID_CONFIRM_COOKIE = "padiem_android_confirm"


def _app():
    store = InMemoryAndroidAuthHandoffStore()
    app = create_app(
        google_settings(),
        auth_transport=_google_transport([]),
        history_store=MemoryHistoryStore(),
        android_handoff_store=store,
    )
    return app, store


def _client(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=BASE_URL, follow_redirects=False
    )


def _claim_headers(secret: str) -> dict[str, str]:
    return {"Accept": "application/json", ANDROID_HANDOFF_SECRET_HEADER: secret}


@pytest.mark.asyncio
async def test_the_creator_cannot_confirm_a_handoff_another_browser_signed_in():
    app, store = _app()
    async with _client(app) as creator, _client(app) as victim:
        payload = (await creator.post("/auth/android/handoff")).json()
        state = httpx.URL(payload["authorization_url"]).params["state"]

        # The other person opens the link and finishes Google in their browser.
        callback = await victim.get(f"/auth/google/callback?state={quote(state)}&code=victim-code")
        assert callback.status_code == 200, callback.text

        # A reload of the callback URL by anyone else never hands out the binding.
        reload = await creator.get(f"/auth/google/callback?state={quote(state)}&code=x")
        assert not [c for c in reload.headers.get_list("set-cookie") if c.startswith(ANDROID_CONFIRM_COOKIE)]

        # The creator posts the state and its own code.
        confirm = await creator.post(
            "/auth/android/confirm", data={"state": state, "user_code": payload["user_code"]}
        )
        assert confirm.status_code == 403, confirm.text
        record = await store.get(payload["handoff_id"])
        assert record.status == HANDOFF_STATUS_AWAITING_CONFIRMATION
        assert record.attempts == 0

        claim = await creator.post(
            f"/auth/android/handoff/{payload['handoff_id']}/claim",
            headers=_claim_headers(payload["claim_secret"]),
        )
        assert claim.status_code == 409
        assert not [c for c in claim.headers.get_list("set-cookie") if c.startswith(SESSION_COOKIE + "=")]


@pytest.mark.asyncio
async def test_the_browser_that_signed_in_still_confirms_and_the_app_claims():
    app, store = _app()
    async with _client(app) as webview, _client(app) as browser:
        payload = (await webview.post("/auth/android/handoff")).json()
        state = httpx.URL(payload["authorization_url"]).params["state"]
        callback = await browser.get(f"/auth/google/callback?state={quote(state)}&code=own-code")
        assert callback.status_code == 200
        confirm = await browser.post(
            "/auth/android/confirm", data={"state": state, "user_code": payload["user_code"]}
        )
        assert confirm.status_code == 200, confirm.text
        assert (await store.get(payload["handoff_id"])).status == HANDOFF_STATUS_READY
        claim = await webview.post(
            f"/auth/android/handoff/{payload['handoff_id']}/claim",
            headers=_claim_headers(payload["claim_secret"]),
        )
        assert claim.status_code == 200, claim.text


@pytest.mark.asyncio
async def test_a_binding_cookie_for_one_handoff_does_not_confirm_another():
    app, _store = _app()
    async with _client(app) as webview, _client(app) as browser, _client(app) as attacker:
        first = (await webview.post("/auth/android/handoff")).json()
        first_state = httpx.URL(first["authorization_url"]).params["state"]
        await attacker.get(f"/auth/google/callback?state={quote(first_state)}&code=own")
        second = (await webview.post("/auth/android/handoff")).json()
        second_state = httpx.URL(second["authorization_url"]).params["state"]
        await browser.get(f"/auth/google/callback?state={quote(second_state)}&code=victim")
        # The attacker holds a valid binding, but for the first handoff only.
        confirm = await attacker.post(
            "/auth/android/confirm", data={"state": second_state, "user_code": second["user_code"]}
        )
        assert confirm.status_code == 403
