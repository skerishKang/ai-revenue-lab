"""#5434 self-service password change for a signed-in account.

The account is resolved from the signed session only, so a request can never
name the account to change. The current password is the proof of ownership,
the new password goes through the same server policy the signup uses, and only
that one credential row moves: the account id, the #5118 role rows and every
other account-owned record stay exactly as they were.
"""
from __future__ import annotations

import asyncio
import re
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.history import D1HistoryStore, _password_user_id, _user_id
from app.main import create_app
from app.password_auth import hash_password, verify_password
from app.platform_admin_roles import D1PlatformAdminRoleStore

BASE = "https://chat.example.test"
ROOT = Path(__file__).resolve().parents[1]
ROLE_MIGRATION = ROOT / "migrations" / "052_platform_admin_roles.sql"
SESSION_SECRET = "5434-password-change-test-session-secret-not-real-00000"
CURRENT_PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "brand new secret phrase"
STATIC = ROOT / "static"


class Statement:
    def __init__(self, db, sql, params=()):
        self.db, self.sql, self.params = db, sql, params

    def bind(self, *params):
        return Statement(self.db, self.sql, params)

    async def first(self):
        row = self.db.conn.execute(self.sql, self.params).fetchone()
        return dict(row) if row else None

    async def run(self):
        cursor = self.db.conn.execute(self.sql, self.params)
        return SimpleNamespace(
            results=[dict(row) for row in cursor.fetchall()],
            meta={"changes": cursor.rowcount},
        )


class SqliteD1:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:", isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")

    def prepare(self, sql):
        return Statement(self, sql)

    async def batch(self, statements):
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            results = []
            for statement in statements:
                cursor = self.conn.execute(statement.sql, statement.params)
                results.append(
                    SimpleNamespace(
                        results=[dict(row) for row in cursor.fetchall()],
                        meta={"changes": cursor.rowcount},
                    )
                )
            self.conn.execute("COMMIT")
            return results
        except Exception:
            self.conn.execute("ROLLBACK")
            raise


class CanonicalAuthority:
    """The minimal canonical authority the change route and the logout share."""

    def __init__(self):
        self.revoked: list[tuple[str, str]] = []

    async def revoke_auth_session(self, *, product_id, session_id):
        self.revoked.append((product_id, session_id))


def seed_db():
    db = SqliteD1()
    db.conn.executescript(
        """
        CREATE TABLE users(
            id TEXT PRIMARY KEY, auth_provider TEXT NOT NULL,
            provider_subject TEXT NOT NULL, email TEXT NOT NULL,
            display_name TEXT NOT NULL, picture_url TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE password_credentials(
            user_id TEXT PRIMARY KEY, username TEXT NOT NULL,
            password_hash TEXT NOT NULL DEFAULT '',
            failed_attempts INTEGER NOT NULL DEFAULT 0,
            locked_until TEXT, created_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        );
        """
    )
    now = "2026-10-01T00:00:00Z"
    owner_uid = _user_id("google-owner")
    owner_email = "owner@example.test"
    member_uid = _password_user_id(owner_email)
    other_uid = _password_user_id("other@example.test")
    for uid, subject, email in (
        (owner_uid, "google-owner", owner_email),
        (member_uid, "password:" + owner_email, owner_email),
        (other_uid, "password:other@example.test", "other@example.test"),
    ):
        db.conn.execute(
            "INSERT INTO users VALUES (?,?,?,?,?,?,?,?)",
            (uid, "google", subject, email, "Owner Test", "", now, now),
        )
    db.conn.execute(
        "INSERT INTO password_credentials(user_id, username, password_hash, "
        "failed_attempts, locked_until, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
        (member_uid, owner_email, hash_password(CURRENT_PASSWORD), 0, None, now, now),
    )
    db.conn.execute(
        "INSERT INTO password_credentials(user_id, username, password_hash, "
        "failed_attempts, locked_until, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
        (other_uid, "other@example.test", hash_password("other account secret"), 0, None, now, now),
    )
    db.conn.executescript(ROLE_MIGRATION.read_text(encoding="utf-8"))
    db.conn.execute(
        "INSERT INTO platform_admin_roles(user_id, role, granted_by, created_at, updated_at) "
        "VALUES (?,?,?,?,?)",
        (member_uid, "ADMIN", owner_uid, now, now),
    )
    return db, {
        "google": owner_uid,
        "member": member_uid,
        "other": other_uid,
        "member_email": owner_email,
    }


def password_settings():
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="password",
        public_base_url=BASE,
        session_secret=SESSION_SECRET,
        session_max_age_seconds=3600,
    )


def build_app(db):
    settings = password_settings()
    authority = CanonicalAuthority()
    app = create_app(
        settings=settings,
        history_store=D1HistoryStore(db),
        control_plane_identity_authority=authority,
    )
    return app, settings, authority


def call(app, settings, method, path, *, token=None, body=None):
    async def inner():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=BASE
        ) as client:
            if token:
                client.cookies.set(SESSION_COOKIE, token)
            return await client.request(method, path, json=body)

    return asyncio.run(inner())


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
    assert unchanged.status_code == 400
    assert unchanged.json()["error"]["code"] == "password_unchanged"

    assert _stored_hash(db, ids["member"]) == before_hash
    assert authority.revoked == []


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
    member_token = create_session_token(settings, ids["member"])
    google_token = create_session_token(settings, ids["google"])

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
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="passwordChangeOpen"' in html
    assert 'id="passwordChangeDialog"' in html
    assert 'id="passwordChangeForm"' in html
    assert 'name="current_password"' in html
    assert 'name="new_password"' in html
    assert re.search(r'id="passwordChangeNew"[^>]*minlength="8"', html)
    assert re.search(r'id="passwordChangeNew"[^>]*maxlength="128"', html)
    # The settings entry is hidden until the server reports a password account.
    assert 'id="accountSettingsSection" hidden' in html


def test_the_browser_posts_only_the_two_password_fields():
    app_js = (STATIC / "app.js").read_text(encoding="utf-8")
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


def test_both_locales_define_the_same_password_change_copy():
    locale = (STATIC / "locale.js").read_text(encoding="utf-8")
    for key in (
        "account-title",
        "password-change-open",
        "password-change-title",
        "password-change-current",
        "password-change-new",
        "password-change-confirm",
        "password-change-submit",
        "password-change-mismatch",
        "password-change-incomplete",
        "password-change-done",
    ):
        assert locale.count(f'"{key}"') == 2, key
