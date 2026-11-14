"""Optional email confirmation (#7679): Chat's signed mail port.

Chat only sends the mail. The signed route, a fake delivery and the real
migration SQLite show that nothing is stored and the token stays in the mail.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re

import httpx
import pytest

from app.config import Settings
from app.email_confirmation import EMAIL_CONFIRMATION_PATH, confirmation_token_digest
from test_email_recovery_7606 import BASE, EMAIL, SECRET, build
from test_password_rpc_261106 import proof_headers


def build_confirm(*, enabled=True):
    app, db, mail = build(enabled=False)  # independent of the recovery switch
    object.__setattr__(app.state.settings, "email_confirmation_enabled", enabled)
    return app, db, mail


def send(app, payload, *, secret=SECRET, headers=None, method="POST"):
    body = json.dumps(payload, separators=(",", ":")).encode()
    signed = proof_headers(secret, EMAIL_CONFIRMATION_PATH, body) if headers is None else headers

    async def call():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client:
            return await client.request(method, EMAIL_CONFIRMATION_PATH, content=body, headers=signed)

    return asyncio.run(call())


def snapshot(db):
    names = [name for (name,) in db.connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name<>'password_rpc_service_ids'")]
    return {name: db.connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0] for name in names}


def test_one_mail_with_the_link_and_only_its_digest_in_the_answer():
    app, db, mail = build_confirm()
    before = snapshot(db)
    answer = send(app, {"email": EMAIL, "lang": "ko"})
    assert answer.status_code == 200
    (message,) = mail.messages
    assert message["to"] == EMAIL and message["subject"] == "[PADIEM] 이메일 확인"
    token = re.search(r"https://auth\.padiem\.net/email/confirm#token=([A-Za-z0-9_-]{43})\s", message["text"]).group(1)
    assert "누르지 않아도 계정은 그대로 쓸 수 있습니다" in message["text"]
    assert answer.json() == {"ok": True, "token_digest": confirmation_token_digest(token)}
    assert re.fullmatch(r"[0-9a-f]{64}", answer.json()["token_digest"])
    assert token not in answer.text
    assert snapshot(db) == before, "Chat keeps no row for a confirmation mail"


def test_chat_and_the_auth_worker_compute_the_same_digest_for_a_link():
    # The same constant is pinned in apps/padiem-auth/test/email-confirmation.test.mjs.
    assert confirmation_token_digest("t" * 43) == "afe9bf3d6c203d28561b28b427cdd6abc285ab1c5b8158a7212e6336644b6d80"


def test_english_mail_and_a_fresh_token_each_time():
    app, _, mail = build_confirm()
    first = send(app, {"email": EMAIL, "lang": "en"}).json()
    second = send(app, {"email": EMAIL, "lang": "en"}).json()
    assert mail.messages[0]["subject"] == "[PADIEM] Confirm your email"
    assert "Your account keeps working even if you do not." in mail.messages[0]["text"]
    assert first["token_digest"] != second["token_digest"]


@pytest.mark.parametrize("result", [False, RuntimeError("synthetic"), None])
def test_a_mail_that_was_not_sent_is_reported_and_names_no_digest(result, caplog):
    app, _, mail = build_confirm()
    if result is None:
        app.state.password_reset_delivery = None
    else:
        mail.result = result
    with caplog.at_level(logging.WARNING):
        answer = send(app, {"email": EMAIL, "lang": "ko"})
    assert (answer.status_code, answer.json()) == (200, {"ok": False})
    lines = [r.getMessage() for r in caplog.records if r.name.endswith("email_confirmation")]
    assert lines == ["email_confirmation reason=" + ("delivery_unconfigured" if result is None else "delivery_failed")]
    assert EMAIL not in " ".join(lines)


def test_the_token_and_the_address_never_reach_a_log_line(caplog):
    app, _, mail = build_confirm()
    with caplog.at_level(logging.DEBUG):
        send(app, {"email": EMAIL, "lang": "ko"})
    token = mail.messages[0]["text"].split("#token=", 1)[1].split()[0]
    assert all(token not in record.getMessage() and EMAIL not in record.getMessage() for record in caplog.records)


@pytest.mark.parametrize("payload", [
    {"email": EMAIL}, {"email": EMAIL, "lang": "fr"}, {"email": "not-an-address", "lang": "ko"},
    {"email": EMAIL, "lang": "ko", "token": "x"}, ["list"],
])
def test_a_malformed_request_sends_nothing(payload):
    app, _, mail = build_confirm()
    assert send(app, payload).status_code == 400
    assert mail.messages == []


def test_unsigned_wrong_secret_and_replayed_calls_are_refused():
    app, _, mail = build_confirm()
    payload = {"email": EMAIL, "lang": "ko"}
    body = json.dumps(payload, separators=(",", ":")).encode()
    assert send(app, payload, headers={"content-type": "application/json"}).status_code == 401
    assert send(app, payload, secret="another-secret-that-is-long-enough-000").status_code == 401
    signed = proof_headers(SECRET, EMAIL_CONFIRMATION_PATH, body)
    assert send(app, payload, headers=signed).status_code == 200
    assert send(app, payload, headers=signed).status_code == 409
    assert len(mail.messages) == 1


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "DELETE"])
def test_switch_off_the_route_does_not_exist_and_no_mail_or_replay_row_is_written(method):
    app, db, mail = build_confirm(enabled=False)
    assert send(app, {"email": EMAIL, "lang": "ko"}, method=method).status_code == 404
    assert mail.messages == []
    assert db.connection.execute("SELECT COUNT(*) FROM password_rpc_service_ids").fetchone()[0] == 0


def test_switch_defaults_off_and_is_read_from_the_host_and_the_worker(monkeypatch):
    from app.worker_config import settings_from_worker_bindings
    monkeypatch.delenv("PADIEM_AUTH_EMAIL_CONFIRMATION_ENABLED", raising=False)
    assert Settings.from_env().email_confirmation_enabled is False
    monkeypatch.setenv("PADIEM_AUTH_EMAIL_CONFIRMATION_ENABLED", "true")
    assert Settings.from_env().email_confirmation_enabled is True
    assert Settings.from_values(email_confirmation_enabled="false").email_confirmation_enabled is False
    assert settings_from_worker_bindings({}).email_confirmation_enabled is False
    assert settings_from_worker_bindings(
        {"PADIEM_AUTH_EMAIL_CONFIRMATION_ENABLED": "true"}).email_confirmation_enabled is True
