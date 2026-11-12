"""#7555 — reset request budget and confirm order.

Covered:

- REFUSED_REQUESTS_ARE_NOT_COUNTED: a refused request neither fills the daily
  budget of an address nor extends its cooldown
- USED_OR_EXPIRED_LINK_ENDS_NOTHING: a used, expired or revoked link is refused
  before any session is ended or any password is stored
- STORE_BEFORE_CONSUME: a failed store leaves the link open for a retry
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_5441_password_reset import (  # noqa: E402
    CURRENT_PASSWORD,
    NEW_PASSWORD,
    CanonicalAuthority,
    RecordingDelivery,
    _stored_hash,
    _token_from_mail,
    build_app,
    confirm_reset,
    request_reset,
    seed_db,
)

from app.password_auth import verify_password  # noqa: E402
from app.password_reset import (  # noqa: E402
    PASSWORD_RESET_DAILY_REQUEST_LIMIT,
    PASSWORD_RESET_REQUEST_COOLDOWN_SECONDS,
)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _age_accepted_rows(db, seconds: int) -> None:
    """Move the rows of the accepted request back in time; refusals stay recent."""
    db.conn.execute(
        "UPDATE password_reset_audit SET occurred_at=? WHERE reason_code IS NULL",
        (_iso(datetime.now(timezone.utc) - timedelta(seconds=seconds)),),
    )


def test_refused_requests_do_not_fill_the_daily_budget():
    db, ids = seed_db()
    delivery = RecordingDelivery()
    app, _settings = build_app(db, delivery=delivery)

    assert request_reset(app, ids["member_email"]).status_code == 202
    refused = [request_reset(app, ids["member_email"]) for _ in range(PASSWORD_RESET_DAILY_REQUEST_LIMIT + 1)]
    assert all(r.status_code == 429 for r in refused)

    # Everything happened more than a cooldown ago: one real request today.
    db.conn.execute(
        "UPDATE password_reset_audit SET occurred_at=?",
        (_iso(datetime.now(timezone.utc) - timedelta(seconds=PASSWORD_RESET_REQUEST_COOLDOWN_SECONDS + 1)),),
    )
    assert request_reset(app, ids["member_email"]).status_code == 202
    assert len(delivery.sent) == 2


def test_refused_requests_do_not_extend_the_cooldown():
    db, ids = seed_db()
    delivery = RecordingDelivery()
    app, _settings = build_app(db, delivery=delivery)

    assert request_reset(app, ids["member_email"]).status_code == 202
    _age_accepted_rows(db, PASSWORD_RESET_REQUEST_COOLDOWN_SECONDS - 10)
    assert request_reset(app, ids["member_email"]).status_code == 429
    # The accepted request is now past the cooldown; the refusal just now is not
    # a request and must not restart it.
    _age_accepted_rows(db, PASSWORD_RESET_REQUEST_COOLDOWN_SECONDS + 1)
    assert request_reset(app, ids["member_email"]).status_code == 202


def test_refused_requests_stay_in_the_audit_ledger():
    db, ids = seed_db()
    app, _settings = build_app(db, delivery=RecordingDelivery())
    request_reset(app, ids["member_email"])
    request_reset(app, ids["member_email"])
    rows = db.conn.execute(
        "SELECT event, reason_code FROM password_reset_audit WHERE reason_code IS NOT NULL"
    ).fetchall()
    assert [(r["event"], r["reason_code"]) for r in rows] == [("rejected", "password_reset_rate_limited")]


def _confirmed_once(db, ids, authority):
    delivery = RecordingDelivery()
    app, _settings = build_app(db, delivery=delivery, authority=authority)
    request_reset(app, ids["member_email"])
    raw = _token_from_mail(delivery)
    return app, raw


def test_a_used_link_ends_no_session_and_changes_nothing():
    db, ids = seed_db()
    authority = CanonicalAuthority()
    app, raw = _confirmed_once(db, ids, authority)
    assert confirm_reset(app, raw).status_code == 200
    authority.revoked_all.clear()
    stored = _stored_hash(db, ids["member"])

    again = confirm_reset(app, raw, new_password="a different new phrase")
    assert again.status_code == 400
    assert again.json()["error"]["code"] == "password_reset_token_used"
    assert authority.revoked_all == []
    assert _stored_hash(db, ids["member"]) == stored


def test_an_expired_link_ends_no_session():
    db, ids = seed_db()
    authority = CanonicalAuthority()
    app, raw = _confirmed_once(db, ids, authority)
    db.conn.execute("UPDATE password_reset_tokens SET expires_at='2026-10-01T00:00:00Z'")

    refused = confirm_reset(app, raw)
    assert refused.status_code == 400
    assert refused.json()["error"]["code"] == "password_reset_token_expired"
    assert authority.revoked_all == []
    assert verify_password(CURRENT_PASSWORD, _stored_hash(db, ids["member"]))


def test_a_revoked_link_ends_no_session():
    db, ids = seed_db()
    authority = CanonicalAuthority()
    app, raw = _confirmed_once(db, ids, authority)
    db.conn.execute("UPDATE password_reset_tokens SET revoked_at='2026-10-01T00:00:00Z'")

    refused = confirm_reset(app, raw)
    assert refused.status_code == 400
    assert refused.json()["error"]["code"] == "password_reset_token_revoked"
    assert authority.revoked_all == []


def test_a_failed_store_keeps_the_link_for_a_retry():
    db, ids = seed_db()
    authority = CanonicalAuthority()
    app, raw = _confirmed_once(db, ids, authority)
    store = app.state.history_store
    real_update = store.update_password_credential
    calls = []

    async def failing_once(user_id, encoded):
        calls.append(user_id)
        if len(calls) == 1:
            raise RuntimeError("storage unavailable")
        return await real_update(user_id, encoded)

    store.update_password_credential = failing_once

    first = confirm_reset(app, raw)
    assert first.status_code == 503
    assert verify_password(CURRENT_PASSWORD, _stored_hash(db, ids["member"]))
    row = db.conn.execute("SELECT consumed_at FROM password_reset_tokens").fetchone()
    assert row["consumed_at"] is None

    second = confirm_reset(app, raw)
    assert second.status_code == 200
    assert verify_password(NEW_PASSWORD, _stored_hash(db, ids["member"]))
    row = db.conn.execute("SELECT consumed_at FROM password_reset_tokens").fetchone()
    assert row["consumed_at"] is not None
