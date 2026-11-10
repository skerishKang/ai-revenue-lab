"""A password change or reset also ends the account's external AI credentials.

The contract this file pins:

* a successful password change revokes every personal token and every OAuth
  grant (access and rotating refresh hashes) of that one account, and never
  touches another account's credentials;
* a successful password reset redemption does the same;
* a personal token minted now carries expires_at = created + TTL (90 days by
  default, configurable), and an expired one is rejected;
* a pre-expiry personal token without expires_at is treated as created_at +
  TTL, never as living forever;
* a failed external revocation never fails the credential change: the change
  answers 200, the failure is journaled without identity, and a durable
  pending row lets the next login retry it.

All ids and secrets in this file are synthetic test material.
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import external_token_revoke
from app.auth import create_session_token
from app.mcp_gateway_store import D1McpGatewayStore, MCP_PAT_TTL_DAYS
from test_5434_password_change import (
    CURRENT_PASSWORD,
    NEW_PASSWORD,
    build_app as build_change_app,
    call as change_call,
    seed_db as seed_change_db,
)
from test_5441_password_reset import (
    RecordingDelivery,
    _token_from_mail,
    build_app as build_reset_app,
    confirm_reset,
    request_reset,
    seed_db as seed_reset_db,
)

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = [
    "085_mcp_gateway.sql",
    "094_mcp_shell_audit.sql",
    "095_mcp_oauth.sql",
    "099_mcp_common_job_receipts.sql",
    "100_mcp_token_device_scope.sql",
    "107_external_token_revoke_pending.sql",
]
DEVICE = "node//test-owner-pc"
NOW = datetime(2026, 11, 10, tzinfo=timezone.utc)
CLIENT_ID = "mcpc_" + "c" * 32
SECRET = "fixed-test-material-not-a-live-credential"


def _apply_mcp_migrations(db):
    for name in MIGRATIONS:
        path = ROOT / "migrations" / name
        if path.exists():
            db.conn.executescript(path.read_text(encoding="utf-8"))


def _store(db, *, ttl=MCP_PAT_TTL_DAYS):
    return D1McpGatewayStore(db, secret_factory=lambda: SECRET, pat_ttl_days=ttl)


def _stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _legacy_row(db, user_id, token_id, token, created_at):
    db.conn.execute(
        "INSERT INTO padiem_mcp_tokens (id,user_id,device_id,name,token_sha256,created_at,kind) "
        "VALUES (?,?,?,?,?,?, 'pat')",
        (token_id, user_id, DEVICE, "Legacy",
         hashlib.sha256(token.encode()).hexdigest(), created_at))


def _seed_with_credentials(seed):
    db, ids = seed()
    _apply_mcp_migrations(db)
    store = _store(db)
    pat = asyncio.run(store.issue_token(
        user_id=ids["member"], device_id=DEVICE, name="Local test", now=NOW))
    oauth = asyncio.run(store.issue_oauth_tokens(
        client_name="Synthetic AI", client_id=CLIENT_ID, user_id=ids["member"],
        device_id=DEVICE, scope="mcp:pc", resource="https://chat.example.test", now=NOW))
    other = asyncio.run(store.issue_token(
        user_id=ids["other"], device_id=DEVICE, name="Other test", now=NOW))
    return db, ids, store, pat, oauth, other


def _revoked(db, token_id) -> bool:
    row = db.conn.execute(
        "SELECT revoked_at FROM padiem_mcp_tokens WHERE id=?", (token_id,)
    ).fetchone()
    return row["revoked_at"] is not None


# --- store: expiry on new tokens -------------------------------------------

@pytest.mark.asyncio
async def test_new_personal_token_carries_the_default_expiry():
    db, ids = seed_change_db()
    _apply_mcp_migrations(db)
    store = _store(db)
    token = await store.issue_token(
        user_id=ids["member"], device_id=DEVICE, name="Local test", now=NOW)
    assert datetime.fromisoformat(token["expires_at"].replace("Z", "+00:00")) == (
        NOW + timedelta(days=MCP_PAT_TTL_DAYS))


@pytest.mark.asyncio
async def test_new_personal_token_expiry_is_configurable():
    db, ids = seed_change_db()
    _apply_mcp_migrations(db)
    store = _store(db, ttl=30)
    token = await store.issue_token(
        user_id=ids["member"], device_id=DEVICE, name="Local test", now=NOW)
    assert datetime.fromisoformat(token["expires_at"].replace("Z", "+00:00")) == (
        NOW + timedelta(days=30))


@pytest.mark.asyncio
async def test_an_expired_personal_token_is_rejected():
    db, ids = seed_change_db()
    _apply_mcp_migrations(db)
    store = _store(db)
    token = await store.issue_token(
        user_id=ids["member"], device_id=DEVICE, name="Local test", now=NOW)
    assert await store.authenticate(token["token"], now=NOW + timedelta(days=89)) is not None
    assert await store.authenticate(token["token"], now=NOW + timedelta(days=90)) is None


# --- store: pre-expiry transition rule -------------------------------------

@pytest.mark.asyncio
async def test_a_legacy_token_without_expiry_counts_created_at_plus_ttl():
    db, ids = seed_change_db()
    _apply_mcp_migrations(db)
    store = _store(db)
    token_id = "mcp_" + "b" * 32
    token = token_id + ".legacy-material-not-a-live-credential"

    for age_days, expected in ((10, "live"), (91, "dead")):
        _legacy_row(db, ids["member"], token_id, token, _stamp(NOW - timedelta(days=age_days)))
        identity = await store.authenticate(token, now=NOW)
        if expected == "live":
            assert identity is not None
        else:
            assert identity is None
        db.conn.execute("DELETE FROM padiem_mcp_tokens WHERE id=?", (token_id,))


# --- store: owner-scoped revoke-all ----------------------------------------

@pytest.mark.asyncio
async def test_revoke_all_tokens_covers_both_kinds_and_spares_other_accounts():
    db, ids = seed_change_db()
    _apply_mcp_migrations(db)
    store = _store(db)
    pat = await store.issue_token(
        user_id=ids["member"], device_id=DEVICE, name="Local test", now=NOW)
    oauth = await store.issue_oauth_tokens(
        client_name="Synthetic AI", client_id=CLIENT_ID, user_id=ids["member"],
        device_id=DEVICE, scope="mcp:pc", resource="https://chat.example.test", now=NOW)
    other = await store.issue_token(
        user_id=ids["other"], device_id=DEVICE, name="Other test", now=NOW)

    assert await store.revoke_all_tokens(user_id=ids["member"]) == 2
    assert await store.authenticate(pat["token"], now=NOW) is None
    assert await store.authenticate(oauth["access_token"], now=NOW) is None
    assert await store.authenticate(other["token"], now=NOW) is not None
    assert await store.revoke_all_tokens(user_id=ids["member"]) == 0


# --- routes: change and reset revoke, failure never fails the change -------

def test_password_change_revokes_external_credentials_and_spares_other_accounts():
    db, ids, store, pat, oauth, other = _seed_with_credentials(seed_change_db)
    app, settings, _authority = build_change_app(db)
    app.state.mcp_gateway_store = store
    app.state.account_data_db = db

    token = create_session_token(
        settings, ids["member"], canonical_session_id="authsession:b62:ext-change")
    response = change_call(
        app, settings, "POST", "/api/auth/password/change",
        token=token,
        body={"current_password": CURRENT_PASSWORD, "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 200
    assert _revoked(db, pat["id"])
    assert _revoked(db, oauth["access_token"].split(".")[0])
    assert not _revoked(db, other["id"])


def test_password_reset_confirm_revokes_external_credentials():
    db, ids, store, pat, oauth, other = _seed_with_credentials(seed_reset_db)
    delivery = RecordingDelivery()
    app, _settings = build_reset_app(db, delivery=delivery)
    app.state.mcp_gateway_store = store
    app.state.account_data_db = db

    request_reset(app, ids["member_email"])
    response = confirm_reset(app, _token_from_mail(delivery))

    assert response.status_code == 200
    assert _revoked(db, pat["id"])
    assert _revoked(db, oauth["access_token"].split(".")[0])
    assert not _revoked(db, other["id"])


def test_password_change_succeeds_when_the_external_revoke_fails_and_retries_later(capsys):
    db, ids, store, pat, oauth, other = _seed_with_credentials(seed_change_db)
    app, settings, _authority = build_change_app(db)
    app.state.account_data_db = db

    class FailingStore:
        async def revoke_all_tokens(self, *, user_id, now=None):
            raise RuntimeError("synthetic store outage")

    app.state.mcp_gateway_store = FailingStore()
    token = create_session_token(
        settings, ids["member"], canonical_session_id="authsession:b62:ext-fail")
    response = change_call(
        app, settings, "POST", "/api/auth/password/change",
        token=token,
        body={"current_password": CURRENT_PASSWORD, "new_password": NEW_PASSWORD},
    )

    # The credential change wins; the external revoke is journaled and parked.
    assert response.status_code == 200
    row = db.conn.execute(
        "SELECT user_id, attempts FROM external_token_revoke_pending"
    ).fetchone()
    assert row["user_id"] == ids["member"]
    assert row["attempts"] >= 1

    out = capsys.readouterr().out
    assert "external_token_revoke" in out
    assert ids["member"] not in out
    assert pat["token"] not in out

    # The next login retries the parked revocation with the real store.
    app.state.mcp_gateway_store = store
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(
            account_data_db=db, mcp_gateway_store=store))
    )
    assert asyncio.run(external_token_revoke.flush_pending(request, ids["member"])) is True
    assert db.conn.execute(
        "SELECT COUNT(*) FROM external_token_revoke_pending").fetchone()[0] == 0
    assert _revoked(db, pat["id"])
    assert _revoked(db, oauth["access_token"].split(".")[0])
    assert not _revoked(db, other["id"])


def test_password_change_without_an_mcp_store_leaves_no_marker():
    db, ids, _store, pat, oauth, other = _seed_with_credentials(seed_change_db)
    app, settings, _authority = build_change_app(db)
    assert getattr(app.state, "mcp_gateway_store", None) is None

    token = create_session_token(
        settings, ids["member"], canonical_session_id="authsession:b62:ext-nostore")
    response = change_call(
        app, settings, "POST", "/api/auth/password/change",
        token=token,
        body={"current_password": CURRENT_PASSWORD, "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 200
    assert db.conn.execute(
        "SELECT COUNT(*) FROM external_token_revoke_pending").fetchone()[0] == 0
    assert not _revoked(db, pat["id"])
