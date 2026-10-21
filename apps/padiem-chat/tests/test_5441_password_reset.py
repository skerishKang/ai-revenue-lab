"""#5441 lost-password self-service reset.

A member who lost the password proves ownership of the account's email address
with a one-time link and then sets the new password themselves. The contract
this file pins:

* an email address alone never changes a password;
* the token is short lived, single use, and a reuse is refused;
* issuance is rate limited so the route cannot become a mail bomb;
* every canonical session of the account is ended before the stored hash moves;
* the account id, the #5118 role rows and every other account-owned record are
  preserved;
* the audit ledger records the lifecycle and never stores the raw token or the
  raw email address.
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
from app.password_reset_store import D1PasswordResetStore

BASE = "https://chat.example.test"
ROOT = Path(__file__).resolve().parents[1]
RESET_MIGRATION = ROOT / "migrations" / "062_password_reset.sql"
ROLE_MIGRATION = ROOT / "migrations" / "052_platform_admin_roles.sql"
SESSION_SECRET = "5441-password-reset-test-session-secret-not-real-000000"
CURRENT_PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "brand new secret phrase"
MEMBER_EMAIL = "member@example.test"
OTHER_EMAIL = "other@example.test"


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


class RecordingDelivery:
    """A network-free mail transport that records what it was asked to send."""

    def __init__(self, *, result: bool = True):
        self.sent: list[dict] = []
        self.result = result

    async def send(self, *, to, subject, text):
        self.sent.append({"to": to, "subject": subject, "text": text})
        return self.result


class CanonicalAuthority:
    """The minimal canonical authority the reset route uses."""

    def __init__(self, *, fail: bool = False):
        self.revoked_all: list[tuple[str, str]] = []
        self.revoked_one: list[tuple[str, str]] = []
        self.fail = fail

    async def revoke_auth_session(self, *, product_id, session_id):
        self.revoked_one.append((product_id, session_id))

    async def revoke_all_auth_sessions(self, *, product_id, product_user_id):
        if self.fail:
            raise RuntimeError("canonical authority is unavailable")
        self.revoked_all.append((product_id, product_user_id))


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
    member_uid = _password_user_id(MEMBER_EMAIL)
    other_uid = _password_user_id(OTHER_EMAIL)
    for uid, subject, email in (
        (owner_uid, "google-owner", "owner@example.test"),
        (member_uid, "password:" + MEMBER_EMAIL, MEMBER_EMAIL),
        (other_uid, "password:" + OTHER_EMAIL, OTHER_EMAIL),
    ):
        db.conn.execute(
            "INSERT INTO users VALUES (?,?,?,?,?,?,?,?)",
            (uid, "google", subject, email, "Member Test", "", now, now),
        )
    db.conn.execute(
        "INSERT INTO password_credentials(user_id, username, password_hash, "
        "failed_attempts, locked_until, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
        (member_uid, MEMBER_EMAIL, hash_password(CURRENT_PASSWORD), 0, None, now, now),
    )
    db.conn.execute(
        "INSERT INTO password_credentials(user_id, username, password_hash, "
        "failed_attempts, locked_until, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
        (other_uid, OTHER_EMAIL, hash_password("other account secret"), 0, None, now, now),
    )
    db.conn.executescript(ROLE_MIGRATION.read_text(encoding="utf-8"))
    db.conn.executescript(RESET_MIGRATION.read_text(encoding="utf-8"))
    db.conn.execute(
        "INSERT INTO platform_admin_roles(user_id, role, granted_by, created_at, updated_at) "
        "VALUES (?,?,?,?,?)",
        (member_uid, "ADMIN", owner_uid, now, now),
    )
    return db, {
        "google": owner_uid,
        "member": member_uid,
        "other": other_uid,
        "member_email": MEMBER_EMAIL,
        "other_email": OTHER_EMAIL,
    }


def password_settings():
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="password",
        public_base_url=BASE,
        session_secret=SESSION_SECRET,
        session_max_age_seconds=3600,
    )


def build_app(db, *, delivery=None, authority=None):
    settings = password_settings()
    app = create_app(
        settings=settings,
        history_store=D1HistoryStore(db),
        password_reset_store=D1PasswordResetStore(db),
        password_reset_delivery=delivery,
        control_plane_identity_authority=authority,
    )
    return app, settings


def call(app, method, path, *, token=None, body=None):
    async def inner():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=BASE
        ) as client:
            if token:
                client.cookies.set(SESSION_COOKIE, token)
            return await client.request(method, path, json=body)

    return asyncio.run(inner())


def request_reset(app, email):
    return call(app, "POST", "/api/auth/password/reset/request", body={"email": email})


def confirm_reset(app, token, new_password=NEW_PASSWORD):
    return call(
        app,
        "POST",
        "/api/auth/password/reset/confirm",
        body={"token": token, "new_password": new_password},
    )


def _token_from_mail(delivery) -> str:
    assert delivery.sent, "no reset mail was sent"
    text = delivery.sent[0]["text"]
    match = re.search(r"#reset=([A-Za-z0-9_\-]+)", text)
    assert match, "the reset mail carries no one-time link"
    return match.group(1)


def _stored_hash(db, user_id) -> str:
    row = db.conn.execute(
        "SELECT password_hash FROM password_credentials WHERE user_id=?", (user_id,)
    ).fetchone()
    return str(row["password_hash"])


def _audit_rows(db):
    return [
        dict(row)
        for row in db.conn.execute(
            "SELECT event, user_id, identifier_digest, reason_code FROM password_reset_audit "
            "ORDER BY id"
        ).fetchall()
    ]


def test_the_request_mails_a_one_time_link_and_never_reveals_an_unknown_account():
    db, ids = seed_db()
    delivery = RecordingDelivery()
    app, _settings = build_app(db, delivery=delivery)

    known = request_reset(app, ids["member_email"])
    unknown = request_reset(app, "nobody@example.test")

    # The public answer is the same for an account that owns a credential and
    # for one that does not, so the route cannot be used to enumerate members.
    assert known.status_code == 202
    assert unknown.status_code == 202
    assert known.json() == unknown.json()
    # Only the real account received a mail.
    assert [mail["to"] for mail in delivery.sent] == [ids["member_email"]]


def test_the_reset_link_carries_the_token_in_the_fragment_not_the_query():
    db, ids = seed_db()
    delivery = RecordingDelivery()
    app, _settings = build_app(db, delivery=delivery)

    request_reset(app, ids["member_email"])

    text = delivery.sent[0]["text"]
    assert "#reset=" in text
    assert "?reset=" not in text
    assert "reset=" not in text.split("#reset=")[0]


def test_the_stored_token_is_a_digest_and_never_the_raw_token():
    db, ids = seed_db()
    delivery = RecordingDelivery()
    app, _settings = build_app(db, delivery=delivery)

    request_reset(app, ids["member_email"])
    raw_token = _token_from_mail(delivery)

    rows = db.conn.execute(
        "SELECT token_digest FROM password_reset_tokens"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["token_digest"] != raw_token
    assert raw_token not in str(dict(rows[0]))


def test_the_audit_ledger_records_the_lifecycle_without_the_raw_token_or_email():
    db, ids = seed_db()
    delivery = RecordingDelivery()
    app, _settings = build_app(db, delivery=delivery)

    request_reset(app, ids["member_email"])
    raw_token = _token_from_mail(delivery)
    confirm_reset(app, raw_token)

    rows = _audit_rows(db)
    events = [row["event"] for row in rows]
    assert "requested" in events
    assert "issued" in events
    assert "delivered" in events
    assert "consumed" in events
    blob = repr(rows)
    assert raw_token not in blob
    assert ids["member_email"] not in blob
    # The identifier is stored as a keyed digest only.
    assert all(
        row["identifier_digest"] and "@" not in row["identifier_digest"]
        for row in rows
    )


def test_the_request_is_rate_limited_per_identifier():
    db, ids = seed_db()
    delivery = RecordingDelivery()
    app, _settings = build_app(db, delivery=delivery)

    first = request_reset(app, ids["member_email"])
    second = request_reset(app, ids["member_email"])

    assert first.status_code == 202
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "password_reset_rate_limited"
    assert len(delivery.sent) == 1


def test_the_request_refuses_honestly_without_a_mail_transport():
    db, ids = seed_db()
    app, _settings = build_app(db, delivery=None)

    response = request_reset(app, ids["member_email"])

    # No fake success: the deployment that cannot send a mail says so.
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "password_reset_delivery_unavailable"
    rows = db.conn.execute("SELECT COUNT(*) AS total FROM password_reset_tokens").fetchone()
    assert rows["total"] == 0


def test_the_confirm_sets_the_new_password_and_preserves_the_account_role_and_data():
    db, ids = seed_db()
    delivery = RecordingDelivery()
    authority = CanonicalAuthority()
    app, settings = build_app(db, delivery=delivery, authority=authority)

    request_reset(app, ids["member_email"])
    raw_token = _token_from_mail(delivery)
    before_hash = _stored_hash(db, ids["member"])

    response = confirm_reset(app, raw_token)

    assert response.status_code == 200
    after_hash = _stored_hash(db, ids["member"])
    assert after_hash != before_hash
    assert verify_password(NEW_PASSWORD, after_hash)
    assert not verify_password(CURRENT_PASSWORD, after_hash)
    # The account, its id and its #5118 role row are untouched.
    row = db.conn.execute(
        "SELECT id, email FROM users WHERE id=?", (ids["member"],)
    ).fetchone()
    assert row["id"] == ids["member"]
    assert row["email"] == ids["member_email"]
    role = db.conn.execute(
        "SELECT role FROM platform_admin_roles WHERE user_id=?", (ids["member"],)
    ).fetchone()
    assert role["role"] == "ADMIN"
    # Another account is untouched.
    assert verify_password("other account secret", _stored_hash(db, ids["other"]))


def test_the_reset_token_is_single_use_and_a_reuse_is_refused():
    db, ids = seed_db()
    delivery = RecordingDelivery()
    authority = CanonicalAuthority()
    app, _settings = build_app(db, delivery=delivery, authority=authority)

    request_reset(app, ids["member_email"])
    raw_token = _token_from_mail(delivery)

    first = confirm_reset(app, raw_token)
    second = confirm_reset(app, raw_token)

    assert first.status_code == 200
    assert second.status_code == 400
    assert second.json()["error"]["code"] == "password_reset_token_used"
    events = [row["event"] for row in _audit_rows(db)]
    assert "rejected" in events


def test_an_expired_reset_token_is_refused():
    db, ids = seed_db()
    delivery = RecordingDelivery()
    authority = CanonicalAuthority()
    app, _settings = build_app(db, delivery=delivery, authority=authority)

    request_reset(app, ids["member_email"])
    raw_token = _token_from_mail(delivery)
    db.conn.execute(
        "UPDATE password_reset_tokens SET expires_at='2026-10-01T00:00:00Z'"
    )

    response = confirm_reset(app, raw_token)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "password_reset_token_expired"
    # The old password still works: an expired link never changes anything.
    assert verify_password(CURRENT_PASSWORD, _stored_hash(db, ids["member"]))


def test_the_confirm_ends_every_canonical_session_of_the_account():
    db, ids = seed_db()
    delivery = RecordingDelivery()
    authority = CanonicalAuthority()
    app, _settings = build_app(db, delivery=delivery, authority=authority)

    request_reset(app, ids["member_email"])
    raw_token = _token_from_mail(delivery)

    confirm_reset(app, raw_token)

    assert authority.revoked_all == [("b62", ids["member"])]


def test_the_confirm_keeps_the_old_password_when_the_session_revocation_fails():
    db, ids = seed_db()
    delivery = RecordingDelivery()
    authority = CanonicalAuthority(fail=True)
    app, _settings = build_app(db, delivery=delivery, authority=authority)

    request_reset(app, ids["member_email"])
    raw_token = _token_from_mail(delivery)
    before_hash = _stored_hash(db, ids["member"])

    response = confirm_reset(app, raw_token)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "session_revocation_failed"
    # Nothing moved: the old password still works and the link can be retried.
    assert _stored_hash(db, ids["member"]) == before_hash
    assert verify_password(CURRENT_PASSWORD, _stored_hash(db, ids["member"]))


def test_a_rejected_new_password_never_burns_the_link():
    db, ids = seed_db()
    delivery = RecordingDelivery()
    authority = CanonicalAuthority()
    app, _settings = build_app(db, delivery=delivery, authority=authority)

    request_reset(app, ids["member_email"])
    raw_token = _token_from_mail(delivery)

    rejected = confirm_reset(app, raw_token, new_password="short")
    assert rejected.status_code == 400
    assert rejected.json()["error"]["code"] == "invalid_password"

    accepted = confirm_reset(app, raw_token)
    assert accepted.status_code == 200
    assert verify_password(NEW_PASSWORD, _stored_hash(db, ids["member"]))


def test_the_confirm_refuses_a_token_that_was_never_issued():
    db, _ids = seed_db()
    delivery = RecordingDelivery()
    app, _settings = build_app(db, delivery=delivery)

    response = confirm_reset(app, "never-issued-token-value")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "password_reset_token_invalid"


def test_the_reset_routes_require_the_password_auth_mode():
    db, ids = seed_db()
    delivery = RecordingDelivery()
    settings = Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url=BASE,
        session_secret=SESSION_SECRET,
        session_max_age_seconds=3600,
        google_client_id="client-id",
        google_client_secret="client-secret",
    )
    app = create_app(
        settings=settings,
        history_store=D1HistoryStore(db),
        password_reset_store=D1PasswordResetStore(db),
        password_reset_delivery=delivery,
    )

    response = request_reset(app, ids["member_email"])

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "auth_unavailable"
