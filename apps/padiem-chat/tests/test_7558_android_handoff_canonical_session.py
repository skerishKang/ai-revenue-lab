"""#7558 — the Android handoff claim binds its cookie to a canonical session.

On an authority-backed deployment the request-time session guard refuses a
``padiem_session`` cookie without a canonical session id once the H2
transition window ends (``auth.SIDELESS_SESSION_ACCEPTED_UNTIL``,
2026-11-18 23:59:59 UTC). The Google callback already establishes the
canonical session for the verified profile; the handoff row now carries that
id to the claim, so an app sign-in keeps working after the window.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest

from app.android_auth_routes import ANDROID_HANDOFF_SECRET_HEADER
from app.android_auth_store import (
    D1AndroidAuthHandoffStore,
    HANDOFF_STATUS_READY,
    InMemoryAndroidAuthHandoffStore,
)
from app.auth import SESSION_COOKIE, decode_session_claims
from app.main import create_app
from test_261110_sidless_session_policy import CanonicalAuthority, ShadowStore
from test_android_auth_handoff import _SqliteD1, _google_transport
from test_auth_history import MemoryHistoryStore, google_settings

BASE_URL = "https://chat.example.test"
PROTECTED_PATH = "/api/conversations"
MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def _app(*, authority=None, shadow=None, handoff_store=None):
    kwargs = {}
    if authority is not None:
        kwargs["control_plane_identity_authority"] = authority
    if shadow is not None:
        kwargs["identity_shadow_store"] = shadow
    store = handoff_store or InMemoryAndroidAuthHandoffStore()
    app = create_app(
        google_settings(),
        auth_transport=_google_transport([]),
        history_store=MemoryHistoryStore(),
        android_handoff_store=store,
        **kwargs,
    )
    return app, store


def _client(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=BASE_URL, follow_redirects=False
    )


def _session_cookie(response: httpx.Response) -> str | None:
    for header in response.headers.get_list("set-cookie"):
        name, _, rest = header.partition("=")
        if name.strip() == SESSION_COOKIE:
            return rest.split(";", 1)[0]
    return None


async def _app_sign_in(app) -> tuple[httpx.Response, str]:
    async with _client(app) as webview, _client(app) as external:
        created = await webview.post("/auth/android/handoff")
        assert created.status_code == 200, created.text
        payload = created.json()
        state = httpx.URL(payload["authorization_url"]).params["state"]
        callback = await external.get(f"/auth/google/callback?state={quote(state)}&code=sample-code")
        assert callback.status_code == 200, callback.text
        confirmed = await external.post(
            "/auth/android/confirm", data={"state": state, "user_code": payload["user_code"]}
        )
        assert confirmed.status_code == 200, confirmed.text
        claimed = await webview.post(
            f"/auth/android/handoff/{payload['handoff_id']}/claim",
            headers={"Accept": "application/json", ANDROID_HANDOFF_SECRET_HEADER: payload["claim_secret"]},
        )
    return claimed, payload["handoff_id"]


@pytest.mark.asyncio
async def test_app_sign_in_after_the_sidless_window_stays_signed_in(monkeypatch):
    authority = CanonicalAuthority()
    app, _store = _app(authority=authority, shadow=ShadowStore())
    claimed, _handoff_id = await _app_sign_in(app)
    assert claimed.status_code == 200, claimed.text
    cookie = _session_cookie(claimed)
    assert cookie
    claims = decode_session_claims(google_settings(), cookie)
    assert claims is not None and claims.canonical_session_id in authority.sessions

    # 2026-11-19 00:00 UTC and later: sid-less cookies are refused.
    monkeypatch.setattr(
        "app.session_revocation_guard.sidless_session_cutoff_passed", lambda now=None: True
    )
    async with _client(app) as webview:
        response = await webview.get(PROTECTED_PATH, headers={"Cookie": f"{SESSION_COOKIE}={cookie}"})
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_authority_backed_claim_without_a_canonical_session_fails_closed():
    authority = CanonicalAuthority()
    app, store = _app(authority=authority, shadow=ShadowStore())
    async with _client(app) as webview:
        created = (await webview.post("/auth/android/handoff")).json()
    handoff_id = created["handoff_id"]
    # A row staged before migration 108: bound user, no canonical session id.
    record = store.records[handoff_id]
    from dataclasses import replace

    store.records[handoff_id] = replace(
        record, status=HANDOFF_STATUS_READY, pending_user_id="usr_" + "a" * 32
    )
    async with _client(app) as webview:
        claimed = await webview.post(
            f"/auth/android/handoff/{handoff_id}/claim",
            headers={"Accept": "application/json", ANDROID_HANDOFF_SECRET_HEADER: created["claim_secret"]},
        )
    assert claimed.status_code == 503
    assert _session_cookie(claimed) is None


@pytest.mark.asyncio
async def test_cookie_only_deployment_keeps_the_unbound_app_cookie():
    app, _store = _app()
    claimed, _handoff_id = await _app_sign_in(app)
    assert claimed.status_code == 200, claimed.text
    claims = decode_session_claims(google_settings(), _session_cookie(claimed))
    assert claims is not None and claims.canonical_session_id is None


@pytest.mark.asyncio
async def test_d1_store_carries_the_canonical_session_id_through_migration_108():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    for name in ("058_android_auth_handoff.sql", "108_android_handoff_canonical_session.sql"):
        connection.executescript((MIGRATIONS / name).read_text(encoding="utf-8"))
    store = D1AndroidAuthHandoffStore(_SqliteD1(connection))
    handoff_id = "aho_" + "d" * 24
    await store.create(
        handoff_id=handoff_id, secret_hash="s", code_hash="c",
        now_iso="2026-11-19T00:00:00Z", expires_at_iso="2026-11-19T00:10:00Z",
    )
    assert (await store.get(handoff_id)).canonical_session_id is None
    assert await store.bind_user(
        handoff_id, user_id="usr_bound", now_iso="2026-11-19T00:01:00Z",
        canonical_session_id="sess_" + "1" * 32,
    )
    assert (await store.get(handoff_id)).canonical_session_id == "sess_" + "1" * 32
