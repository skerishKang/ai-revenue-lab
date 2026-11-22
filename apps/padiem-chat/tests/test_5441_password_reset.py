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

from _support.password_reset import (
    BASE,
    CURRENT_PASSWORD,
    CanonicalAuthority,
    MEMBER_EMAIL,
    NEW_PASSWORD,
    OTHER_EMAIL,
    RESET_MIGRATION,
    ROLE_MIGRATION,
    ROOT,
    RecordingDelivery,
    SESSION_SECRET,
    SqliteD1,
    Statement,
    _stored_hash,
    _token_from_mail,
    build_app,
    call,
    confirm_reset,
    password_settings,
    request_reset,
    seed_db,
)



























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
