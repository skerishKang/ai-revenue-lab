"""#5434 self-service password change for a signed-in account.

The account is resolved from the signed session only, so a request can never
name the account to change. The current password is the proof of ownership,
the new password goes through the same server policy the signup uses, and only
that one credential row moves: the account id, the #5118 role rows and every
other account-owned record stay exactly as they were.
"""
from __future__ import annotations
import locale_bundle

import asyncio
import re
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
# #8061: 공용 준비(비밀번호 상수·seed_db·build_app·call)는
# _support/password_change가 소유한다.
from _support.password_change import (
    BASE, CURRENT_PASSWORD, NEW_PASSWORD, CanonicalAuthority, build_app, call,
    password_settings, seed_db)
from app.config import Settings
from app.history import D1HistoryStore, _password_user_id, _user_id
from app.main import create_app
from app.password_auth import hash_password, verify_password
from app.platform_admin_roles import D1PlatformAdminRoleStore
from _support import password_change_static as change_assets

ROOT = Path(__file__).resolve().parents[1]
ROLE_MIGRATION = ROOT / "migrations" / "052_platform_admin_roles.sql"
STATIC = ROOT / "static"


def _stored_hash(db, user_id) -> str:
    row = db.conn.execute(
        "SELECT password_hash FROM password_credentials WHERE user_id=?", (user_id,)
    ).fetchone()
    return str(row["password_hash"])


def test_the_change_replaces_the_hash_and_preserves_the_account_and_role():
    db, ids = seed_db()
    app, settings, authority = build_app(db)
    token = create_session_token(
        settings, ids["member"], canonical_session_id="authsession:b62:5434"
    )
    before_hash = _stored_hash(db, ids["member"])

    response = call(
        app,
        settings,
        "POST",
        "/api/auth/password/change",
        token=token,
        body={"current_password": CURRENT_PASSWORD, "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    # The session that changed the credential is ended, so a stored copy of the
    # cookie stops working and the browser signs in again.
    assert "padiem_session=" in response.headers.get("set-cookie", "")
    assert authority.revoked == [("b62", "authsession:b62:5434")]

    after_hash = _stored_hash(db, ids["member"])
    assert after_hash != before_hash
    assert verify_password(NEW_PASSWORD, after_hash) is True
    assert verify_password(CURRENT_PASSWORD, after_hash) is False

    # The account id, the credential subject, the account row and the #5118
    # role row are untouched.
    credential = db.conn.execute(
        "SELECT user_id, username FROM password_credentials WHERE user_id=?",
        (ids["member"],),
    ).fetchone()
    assert tuple(credential) == (ids["member"], ids["member_email"])
    account = db.conn.execute(
        "SELECT id, auth_provider, provider_subject, email, display_name "
        "FROM users WHERE id=?",
        (ids["member"],),
    ).fetchone()
    assert tuple(account) == (
        ids["member"],
        "google",
        "password:" + ids["member_email"],
        ids["member_email"],
        "Owner Test",
    )
    role = db.conn.execute(
        "SELECT user_id, role FROM platform_admin_roles WHERE user_id=?",
        (ids["member"],),
    ).fetchone()
    assert tuple(role) == (ids["member"], "ADMIN")
    assert asyncio.run(D1PlatformAdminRoleStore(db).role_for(ids["member"])) == "ADMIN"

    # The old password no longer signs in; the new one does.
    old_login = call(
        app,
        settings,
        "POST",
        "/api/auth/password/login",
        body={"identifier": ids["member_email"], "password": CURRENT_PASSWORD},
    )
    assert old_login.status_code == 401
    new_login = call(
        app,
        settings,
        "POST",
        "/api/auth/password/login",
        body={"identifier": ids["member_email"], "password": NEW_PASSWORD},
    )
    assert new_login.status_code == 200
    assert new_login.json()["user"]["email"] == ids["member_email"]


def test_a_wrong_current_password_changes_nothing():
    db, ids = seed_db()
    app, settings, authority = build_app(db)
    token = create_session_token(
        settings, ids["member"], canonical_session_id="authsession:b62:5434"
    )
    before_hash = _stored_hash(db, ids["member"])

    response = call(
        app,
        settings,
        "POST",
        "/api/auth/password/change",
        token=token,
        body={"current_password": "not the current password", "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"
    assert _stored_hash(db, ids["member"]) == before_hash
    assert authority.revoked == []


def test_the_new_password_uses_the_same_server_policy_as_the_signup():
    db, ids = seed_db()
    app, settings, authority = build_app(db)
    token = create_session_token(
        settings, ids["member"], canonical_session_id="authsession:b62:5434"
    )
    before_hash = _stored_hash(db, ids["member"])

    too_short = call(
        app,
        settings,
        "POST",
        "/api/auth/password/change",
        token=token,
        body={"current_password": CURRENT_PASSWORD, "new_password": "1234567"},
    )
    assert too_short.status_code == 400
    assert too_short.json()["error"]["code"] == "invalid_password"
    assert "8~128" in too_short.json()["error"]["message"]

    contains_identifier = call(
        app,
        settings,
        "POST",
        "/api/auth/password/change",
        token=token,
        body={
            "current_password": CURRENT_PASSWORD,
            "new_password": ids["member_email"] + " secret",
        },
    )
    assert contains_identifier.status_code == 400
    assert contains_identifier.json()["error"]["code"] == "invalid_password"

    unchanged = call(
        app,
        settings,
        "POST",
        "/api/auth/password/change",
        token=token,
        body={"current_password": CURRENT_PASSWORD, "new_password": CURRENT_PASSWORD},
    )
    # The server replaces the hash with a fresh salt. The same-password guard
    # is a client-side step-up affordance, not a server-side policy: refusing
    # it here would cost a third key derivation, which is what the Worker's CPU
    # budget cannot afford.
    assert unchanged.status_code == 200
    assert _stored_hash(db, ids["member"]) != before_hash

    assert authority.revoked != []


def test_the_change_route_runs_at_most_two_key_derivations(monkeypatch):
    """One request must not derive more keys than the login path already does.

    A third key derivation in this route pushed the request past the
    Worker's CPU limit and the route answered 503 in Production. The login
    path derives exactly one key per request, so the change route may afford
    the ownership proof and the new hash, and nothing more.
    """
    import app.password_auth as password_auth

    db, ids = seed_db()
    app, settings, _authority = build_app(db)
    token = create_session_token(
        settings, ids["member"], canonical_session_id="authsession:b62:5434"
    )

    derivations: list[str] = []
    original = password_auth.hashlib.pbkdf2_hmac

    def counting(*args, **kwargs):
        derivations.append("pbkdf2")
        return original(*args, **kwargs)

    monkeypatch.setattr(password_auth.hashlib, "pbkdf2_hmac", counting)
    response = call(
        app,
        settings,
        "POST",
        "/api/auth/password/change",
        token=token,
        body={"current_password": CURRENT_PASSWORD, "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 200
    assert len(derivations) == 2


def test_a_request_can_never_name_another_account():
    db, ids = seed_db()
    app, settings, authority = build_app(db)
    token = create_session_token(
        settings, ids["member"], canonical_session_id="authsession:b62:5434"
    )
    other_hash = _stored_hash(db, ids["other"])
    member_hash = _stored_hash(db, ids["member"])

    response = call(
        app,
        settings,
        "POST",
        "/api/auth/password/change",
        token=token,
        body={
            "current_password": CURRENT_PASSWORD,
            "new_password": NEW_PASSWORD,
            "user_id": ids["other"],
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert _stored_hash(db, ids["other"]) == other_hash
    assert _stored_hash(db, ids["member"]) == member_hash
    assert authority.revoked == []


def test_an_unauthenticated_request_is_refused():
    db, ids = seed_db()
    app, settings, authority = build_app(db)
    before_hash = _stored_hash(db, ids["member"])

    response = call(
        app,
        settings,
        "POST",
        "/api/auth/password/change",
        body={"current_password": CURRENT_PASSWORD, "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"
    assert _stored_hash(db, ids["member"]) == before_hash
    assert authority.revoked == []


def test_a_google_only_account_has_no_password_to_change():
    db, ids = seed_db()
    app, settings, authority = build_app(db)
    token = create_session_token(
        settings, ids["google"], canonical_session_id="authsession:b62:5434"
    )

    response = call(
        app,
        settings,
        "POST",
        "/api/auth/password/change",
        token=token,
        body={"current_password": CURRENT_PASSWORD, "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "password_change_unavailable"
    assert authority.revoked == []


def test_the_auth_status_reports_the_account_method():
    db, ids = seed_db()
    app, settings, _ = build_app(db)
    member_token = create_session_token(settings, ids["member"], canonical_session_id="session_test_a")
    google_token = create_session_token(settings, ids["google"], canonical_session_id="session_test_a")

    member = call(app, settings, "GET", "/api/auth/status", token=member_token)
    assert member.status_code == 200
    assert member.json()["account_method"] == "password"

    google = call(app, settings, "GET", "/api/auth/status", token=google_token)
    assert google.status_code == 200
    assert google.json()["account_method"] == "google"

    guest = call(app, settings, "GET", "/api/auth/status")
    assert guest.status_code == 200
    assert "account_method" not in guest.json()


def test_the_account_settings_offer_the_change_in_the_served_markup():
    for element_id in ("passwordChangeOpen", "passwordChangeDialog",
                       "passwordChangeForm", "passwordChangeCurrent", "passwordChangeNew"):
        assert change_assets.element(element_id) is not None, element_id
    current_field = change_assets.element("passwordChangeCurrent")[1]
    assert current_field["name"] == "current_password"
    new_field = change_assets.element("passwordChangeNew")[1]
    assert new_field["name"] == "new_password"
    assert new_field["minlength"] == "8"
    assert new_field["maxlength"] == "128"
    # The advanced settings page carries the password block; it stays hidden
    # until the server reports a password account.
    assert "hidden" in change_assets.element("advancedAccountSection")[1]
    assert "hidden" in change_assets.element("accountPasswordActions")[1]
    assert (change_assets.element_index("advancedAccountSection")
            < change_assets.element_index("passwordChangeOpen"))


def test_the_browser_posts_only_the_two_password_fields():
    #7216 R5 step 4: this contract moved into chat-auth-module.js.
    app_js = change_assets.account_module_source()
    payload = re.search(
        r'passwordAuthRequest\("/api/auth/password/change",\s*\{(?P<body>.*?)\}\)',
        app_js,
        re.S,
    )
    assert payload is not None, "the password change request must exist"
    body = payload.group("body")
    assert "current_password" in body
    assert "new_password" in body
    assert "user_id" not in body
    assert "email" not in body


def test_the_browser_refuses_a_new_password_equal_to_the_current_one():
    """The same-password guard lives in the browser, so the server stays cheap."""
    #7216 R5 step 4: this contract moved into chat-auth-module.js.
    app_js = change_assets.account_module_source()
    assert "password-change-unchanged" in app_js
    assert "newPassword === currentPassword" in app_js


def test_both_locales_define_the_same_password_change_copy():
    counts = change_assets.locale_key_counts()
    for key in (
        "account-title",
        "password-change-open",
        "password-change-title",
        "password-change-current",
        "password-change-new",
        "password-change-confirm",
        "password-change-submit",
        "password-change-mismatch",
        "password-change-unchanged",
        "password-change-incomplete",
        "password-change-done",
    ):
        assert counts.get(key) == 2, key
