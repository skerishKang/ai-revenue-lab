"""Android 1.0.1 external-browser sign-in return contract.

The WebView keeps the session. The external browser completes Google and
confirms with a code shown inside the app. These tests pin the load-bearing
properties: no session cookie reaches the external browser, a signed state
alone never authenticates, the claim is single-use and secret-guarded, the
standard cookie flow is untouched, and the D1 migration/guards are real SQL.
"""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest

from app.android_auth_routes import (
    ANDROID_HANDOFF_CONFIRM_ATTEMPTS,
    ANDROID_HANDOFF_SECRET_HEADER,
)
from app.android_auth_store import (
    D1AndroidAuthHandoffStore,
    HANDOFF_STATUS_AWAITING_CONFIRMATION,
    HANDOFF_STATUS_CANCELLED,
    HANDOFF_STATUS_CLAIMED,
    HANDOFF_STATUS_READY,
    InMemoryAndroidAuthHandoffStore,
)
from app.auth import (
    GOOGLE_TOKEN_URL,
    GOOGLE_USERINFO_URL,
    OAUTH_STATE_COOKIE,
    SESSION_COOKIE,
    create_android_handoff_state,
    create_oauth_state,
    verify_android_handoff_state,
    verify_oauth_state,
)
from app.main import create_app
from test_auth_history import MemoryHistoryStore, google_settings

BASE_URL = "https://chat.example.test"
MIGRATION_PATH = Path(__file__).resolve().parents[1] / "migrations" / "058_android_auth_handoff.sql"


def _google_transport(calls: list[str], *, access_token: str = "handoff-access-token") -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if str(request.url) == GOOGLE_TOKEN_URL:
            return httpx.Response(
                200,
                json={"access_token": access_token, "token_type": "Bearer", "expires_in": 3600},
            )
        if str(request.url) == GOOGLE_USERINFO_URL:
            assert request.headers.get("Authorization") == f"Bearer {access_token}"
            return httpx.Response(
                200,
                json={
                    "id": "android-subject-0001",
                    "email": "android@example.test",
                    "verified_email": True,
                    "name": "Android User",
                    "picture": "",
                },
            )
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _app(handoff_store=None, calls=None):
    store = MemoryHistoryStore()
    app = create_app(
        google_settings(),
        auth_transport=_google_transport(calls if calls is not None else []),
        history_store=store,
        android_handoff_store=handoff_store or InMemoryAndroidAuthHandoffStore(),
    )
    return app, store


def _client(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=BASE_URL,
        follow_redirects=False,
    )


async def _create_handoff(client: httpx.AsyncClient) -> tuple[dict, str]:
    response = await client.post("/auth/android/handoff")
    assert response.status_code == 200, response.text
    payload = response.json()
    state = httpx.URL(payload["authorization_url"]).params["state"]
    return payload, state


async def _confirm(client: httpx.AsyncClient, state: str, code: str) -> httpx.Response:
    return await client.post("/auth/android/confirm", data={"state": state, "user_code": code})


def _status_headers(secret: str) -> dict[str, str]:
    return {"Accept": "application/json", ANDROID_HANDOFF_SECRET_HEADER: secret}


@pytest.mark.asyncio
async def test_handoff_create_returns_bounded_secret_code_and_canonical_redirect() -> None:
    calls: list[str] = []
    app, _store = _app(calls=calls)
    async with _client(app) as client:
        response = await client.post("/auth/android/handoff")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"handoff_id", "claim_secret", "user_code", "authorization_url", "expires_in"}
    assert payload["handoff_id"].startswith("aho_")
    assert len(payload["claim_secret"]) >= 16
    assert payload["user_code"][4] == "-"
    assert payload["expires_in"] == 600
    assert response.headers["cache-control"].startswith("no-store")
    assert response.headers.get_list("set-cookie") == []
    # Neither the long-lived secret nor the displayed code may ride a URL.
    assert payload["claim_secret"] not in payload["authorization_url"]
    assert payload["user_code"].replace("-", "") not in payload["authorization_url"]
    url = httpx.URL(payload["authorization_url"])
    assert url.params["state"]
    assert url.params["state"] != payload["claim_secret"]
    assert url.params["redirect_uri"] == f"{BASE_URL}/auth/google/callback"
    assert calls == []


@pytest.mark.asyncio
async def test_full_handoff_never_gives_the_external_browser_a_session() -> None:
    calls: list[str] = []
    handoff_store = InMemoryAndroidAuthHandoffStore()
    app, store = _app(handoff_store=handoff_store, calls=calls)
    async with _client(app) as webview, _client(app) as external:
        payload, state = await _create_handoff(webview)
        handoff_id = payload["handoff_id"]

        callback = await external.get(
            f"/auth/google/callback?state={quote(state)}&code=sample-code"
        )
        assert callback.status_code == 200, callback.text
        assert "로그인 확인" in callback.text
        assert 'name="user_code"' in callback.text
        assert not [
            value for value in callback.headers.get_list("set-cookie")
            if value.startswith(SESSION_COOKIE + "=")
        ]
        assert calls == [GOOGLE_TOKEN_URL, GOOGLE_USERINFO_URL]

        record = await handoff_store.get(handoff_id)
        assert record is not None
        assert record.status == HANDOFF_STATUS_AWAITING_CONFIRMATION
        assert record.pending_user_id
        assert callback.text != "" and payload["claim_secret"] not in callback.text
        assert payload["user_code"].replace("-", "") not in callback.text

        pending = await webview.get(
            f"/auth/android/handoff/{handoff_id}", headers=_status_headers(payload["claim_secret"])
        )
        assert pending.json()["status"] == HANDOFF_STATUS_AWAITING_CONFIRMATION

        early_claim = await webview.post(
            f"/auth/android/handoff/{handoff_id}/claim",
            headers=_status_headers(payload["claim_secret"]),
        )
        assert early_claim.status_code == 409
        assert early_claim.json()["error"]["code"] == "android_handoff_pending"
        assert early_claim.headers.get_list("set-cookie") == []

        # The external browser may carry an unrelated stale session cookie; the
        # urlencoded confirm form must still work and must not consult it.
        external.cookies.set(SESSION_COOKIE, "stale-external-browser-session", domain="chat.example.test", path="/")
        confirmed = await _confirm(external, state, payload["user_code"])
        assert confirmed.status_code == 200, confirmed.text
        assert "로그인이 확인되었습니다" in confirmed.text

        ready = await webview.get(
            f"/auth/android/handoff/{handoff_id}", headers=_status_headers(payload["claim_secret"])
        )
        assert ready.json()["status"] == HANDOFF_STATUS_READY

        wrong_secret = await webview.post(
            f"/auth/android/handoff/{handoff_id}/claim",
            headers={ANDROID_HANDOFF_SECRET_HEADER: "x" * 32},
        )
        assert wrong_secret.status_code == 404

        claimed = await webview.post(
            f"/auth/android/handoff/{handoff_id}/claim",
            headers=_status_headers(payload["claim_secret"]),
        )
        assert claimed.status_code == 200, claimed.text
        assert claimed.json() == {"authenticated": True}
        set_cookies = claimed.headers.get_list("set-cookie")
        session_cookie = next(value for value in set_cookies if value.startswith(SESSION_COOKIE + "="))
        assert "HttpOnly" in session_cookie
        assert "Secure" in session_cookie
        assert "SameSite=lax" in session_cookie

        status = await webview.get("/api/auth/status")
        assert status.json()["authenticated"] is True
        assert status.json()["user"]["email"] == "android@example.test"

        replay = await webview.post(
            f"/auth/android/handoff/{handoff_id}/claim",
            headers={**_status_headers(payload["claim_secret"]), "Origin": BASE_URL},
        )
        assert replay.status_code == 409
        assert replay.json()["error"]["code"] == "android_handoff_claimed"
        record = await handoff_store.get(handoff_id)
        assert record is not None and record.status == HANDOFF_STATUS_CLAIMED
        assert len(store.users) == 1


@pytest.mark.asyncio
async def test_callback_reload_renders_the_code_form_without_a_second_exchange() -> None:
    calls: list[str] = []
    app, _store = _app(calls=calls)
    async with _client(app) as webview, _client(app) as external:
        payload, state = await _create_handoff(webview)
        first = await external.get(f"/auth/google/callback?state={quote(state)}&code=first")
        second = await external.get(f"/auth/google/callback?state={quote(state)}&code=second")
    assert first.status_code == 200
    assert second.status_code == 200
    assert 'name="user_code"' in second.text
    assert calls == [GOOGLE_TOKEN_URL, GOOGLE_USERINFO_URL]


@pytest.mark.asyncio
async def test_tampered_handoff_state_is_rejected_before_any_google_call() -> None:
    calls: list[str] = []
    app, _store = _app(calls=calls)
    async with _client(app) as webview, _client(app) as external:
        _payload, state = await _create_handoff(webview)
        response = await external.get(
            f"/auth/google/callback?state={quote(state + 'x')}&code=sample-code"
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_oauth_state"
    assert calls == []
    assert not [value for value in response.headers.get_list("set-cookie") if value.startswith(SESSION_COOKIE + "=")]


@pytest.mark.asyncio
async def test_wrong_code_is_bounded_and_cancels_the_handoff() -> None:
    app, _store = _app()
    async with _client(app) as webview, _client(app) as external:
        payload, state = await _create_handoff(webview)
        handoff_id = payload["handoff_id"]
        await external.get(f"/auth/google/callback?state={quote(state)}&code=sample-code")

        first_wrong = await _confirm(external, state, "AAAA-AAAA")
        assert first_wrong.status_code == 400
        assert "남은 시도: 9회" in first_wrong.text

        last = first_wrong
        for _attempt in range(ANDROID_HANDOFF_CONFIRM_ATTEMPTS - 1):
            last = await _confirm(external, state, "AAAA-AAAA")
        assert last.status_code == 410

        record = await app.state.android_handoff_store.get(handoff_id)
        assert record is not None
        assert record.status == HANDOFF_STATUS_CANCELLED
        assert record.attempts == ANDROID_HANDOFF_CONFIRM_ATTEMPTS

        # The code shown in the app is no longer usable and cannot be claimed.
        correct_after_cancel = await _confirm(external, state, payload["user_code"])
        assert correct_after_cancel.status_code == 410
        claim = await webview.post(
            f"/auth/android/handoff/{handoff_id}/claim",
            headers=_status_headers(payload["claim_secret"]),
        )
        assert claim.status_code == 410
        assert claim.json()["error"]["code"] == "android_handoff_expired"


@pytest.mark.asyncio
async def test_expired_handoff_reports_expired_and_refuses_claim() -> None:
    handoff_store = InMemoryAndroidAuthHandoffStore()
    app, _store = _app(handoff_store=handoff_store)
    async with _client(app) as webview:
        payload, _state = await _create_handoff(webview)
        handoff_id = payload["handoff_id"]
        handoff_store.records[handoff_id] = replace(
            handoff_store.records[handoff_id], expires_at="2000-01-01T00:00:00Z"
        )
        status = await webview.get(
            f"/auth/android/handoff/{handoff_id}", headers=_status_headers(payload["claim_secret"])
        )
        claim = await webview.post(
            f"/auth/android/handoff/{handoff_id}/claim",
            headers=_status_headers(payload["claim_secret"]),
        )
    assert status.json()["status"] == "expired"
    assert claim.status_code == 410


def test_handoff_state_purpose_is_separate_from_the_oauth_cookie_state() -> None:
    settings = google_settings()
    handoff_id = "aho_" + "a" * 24
    signed_handoff = create_android_handoff_state(settings, handoff_id)
    assert verify_android_handoff_state(settings, signed_handoff) == handoff_id
    assert verify_android_handoff_state(settings, signed_handoff + "x") is None

    state, signed_oauth = create_oauth_state(settings)
    assert verify_android_handoff_state(settings, signed_oauth) is None
    assert not verify_oauth_state(settings, signed_handoff, signed_handoff)
    assert verify_oauth_state(settings, state, signed_oauth)


@pytest.mark.asyncio
async def test_handoff_create_fails_closed_without_a_store() -> None:
    app = create_app(google_settings(), history_store=MemoryHistoryStore())
    assert app.state.android_handoff_store is None
    async with _client(app) as client:
        response = await client.post("/auth/android/handoff")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "android_handoff_unavailable"


class _SqliteD1:
    """Minimal D1-shaped adapter so the migration and guards run as real SQL."""

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def prepare(self, sql: str) -> "_SqliteStatement":
        return _SqliteStatement(self.connection, sql)


class _SqliteStatement:
    def __init__(self, connection: sqlite3.Connection, sql: str):
        self.connection = connection
        self.sql = sql
        self.params: tuple = ()

    def bind(self, *params):
        self.params = params
        return self

    async def first(self):
        cursor = self.connection.execute(self.sql, self.params)
        row = cursor.fetchone()
        self.connection.commit()
        return dict(row) if row is not None else None


def _sqlite_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(MIGRATION_PATH.read_text(encoding="utf-8"))
    return connection


@pytest.mark.asyncio
async def test_d1_store_transitions_are_atomic_and_guarded_by_migration_058() -> None:
    connection = _sqlite_connection()
    try:
        store = D1AndroidAuthHandoffStore(_SqliteD1(connection))
        await store.create(
            handoff_id="aho_" + "b" * 24,
            secret_hash="secret-hash",
            code_hash="code-hash",
            now_iso="2026-10-19T00:00:00Z",
            expires_at_iso="2026-10-19T00:10:00Z",
        )
        record = await store.get("aho_" + "b" * 24)
        assert record is not None
        assert record.status == "awaiting_login"
        assert record.attempts == 0
        assert record.pending_user_id is None

        assert await store.bind_user(
            "aho_" + "b" * 24, user_id="usr_existing", now_iso="2026-10-19T00:01:00Z"
        )
        # A second bind cannot repoint a confirmed handoff at another account.
        assert not await store.bind_user(
            "aho_" + "b" * 24, user_id="usr_attacker", now_iso="2026-10-19T00:01:00Z"
        )
        assert not await store.confirm(
            "aho_" + "b" * 24, code_hash="wrong", now_iso="2026-10-19T00:02:00Z"
        )
        attempts = await store.record_failed_attempt(
            "aho_" + "b" * 24, maximum=3, now_iso="2026-10-19T00:02:00Z"
        )
        assert attempts == 1
        assert await store.confirm(
            "aho_" + "b" * 24, code_hash="code-hash", now_iso="2026-10-19T00:02:00Z"
        )
        record = await store.get("aho_" + "b" * 24)
        assert record is not None and record.status == HANDOFF_STATUS_READY

        assert await store.claim(
            "aho_" + "b" * 24, secret_hash="wrong", now_iso="2026-10-19T00:03:00Z"
        ) is None
        assert await store.claim(
            "aho_" + "b" * 24, secret_hash="secret-hash", now_iso="2026-10-19T00:03:00Z"
        ) == "usr_existing"
        assert await store.claim(
            "aho_" + "b" * 24, secret_hash="secret-hash", now_iso="2026-10-19T00:03:00Z"
        ) is None

        await store.create(
            handoff_id="aho_" + "c" * 24,
            secret_hash="expired-secret",
            code_hash="expired-code",
            now_iso="2026-10-18T00:00:00Z",
            expires_at_iso="2026-10-18T00:10:00Z",
        )
        assert not await store.bind_user(
            "aho_" + "c" * 24, user_id="usr_existing", now_iso="2026-10-19T00:00:00Z"
        )
        assert await store.claim(
            "aho_" + "c" * 24, secret_hash="expired-secret", now_iso="2026-10-19T00:00:00Z"
        ) is None

        abandoned = await store.get("aho_" + "c" * 24)
        assert abandoned is not None and abandoned.pending_user_id is None
    finally:
        connection.close()
