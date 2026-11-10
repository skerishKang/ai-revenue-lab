"""#7078: password change/reset revoke the user's padiem-auth sessions.

The Chat session revocation stays strict. The shared-login revocation is
best-effort by product decision: it never fails the credential change, leaves a
bounded log line and a durable retry marker. All tests carry synthetic ids.
"""
from __future__ import annotations

import asyncio
import hashlib
from types import SimpleNamespace

import httpx
import pytest

from test_5434_password_change import (
    CURRENT_PASSWORD as CHANGE_CURRENT,
    NEW_PASSWORD as CHANGE_NEW,
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
from app.auth import create_session_token
from app import shared_session_revoke

USER_ONE = "usr_" + "a" * 32
SECRET = "synthetic-account-delete-secret-32chars"


def _request(transport, *, db=None):
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=SimpleNamespace(account_delete_rpc_secret=SECRET),
                account_delete_rpc_transport=transport,
                account_data_db=db,
            )
        )
    )


class _Transport:
    def __init__(self, status=200, payload=None, error=None):
        self.status = status
        self.payload = {"ok": True, "accounts": 1, "revoked_sessions": 2} if payload is None else payload
        self.error = error
        self.calls = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(status_code=self.status, json=lambda: self.payload)


class _Statement:
    def __init__(self, db, sql):
        self.db, self.sql = db, sql
        self.params = ()

    def bind(self, *params):
        self.params = params
        return self

    async def run(self):
        self.db.runs.append((self.sql, self.params))
        return SimpleNamespace(meta={"changes": 1})

    async def first(self):
        self.db.reads.append(self.sql)
        return self.db.row


class _Db:
    def __init__(self, row=None):
        self.row = row
        self.runs = []
        self.reads = []

    def prepare(self, sql):
        return _Statement(self, sql)


def test_the_signed_revoke_call_carries_only_the_chat_user():
    transport = _Transport()
    ok = asyncio.run(shared_session_revoke.revoke_after_credential_change(_request(transport), USER_ONE))
    assert ok is True
    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["path"] == "/internal/account-sessions/revoke"
    body = call["body"].decode("utf-8")
    assert body == '{"product_id":"b62","product_user_id":"' + USER_ONE + '"}'
    assert USER_ONE not in call["headers"]["x-padiem-service-proof"]


def test_a_failed_revoke_never_raises_and_leaves_a_retry_marker(capsys):
    db = _Db()
    transport = _Transport(error=RuntimeError("transport down"))
    ok = asyncio.run(
        shared_session_revoke.revoke_after_credential_change(_request(transport, db=db), USER_ONE)
    )
    assert ok is False
    assert any("shared_session_revoke_pending" in sql for sql, _ in db.runs)
    out = capsys.readouterr().out
    assert "shared_session_revoke" in out
    assert USER_ONE not in out
    assert hashlib.sha256(USER_ONE.encode()).hexdigest() not in out


def test_flush_retries_a_pending_row_and_removes_it_on_success():
    db = _Db(row={"user_id": USER_ONE})
    transport = _Transport()
    ok = asyncio.run(shared_session_revoke.flush_pending(_request(transport, db=db), USER_ONE))
    assert ok is True
    assert any("DELETE FROM shared_session_revoke_pending" in sql for sql, _ in db.runs)


def test_password_change_calls_the_shared_revoke_even_when_it_fails(monkeypatch):
    calls = []
    async def failing(request, user_id):
        calls.append(user_id)
        return False
    monkeypatch.setattr(shared_session_revoke, "revoke_after_credential_change", failing)

    db, ids = seed_change_db()
    app, settings, _authority = build_change_app(db)
    token = create_session_token(settings, ids["member"], canonical_session_id="authsession:b62:7078")
    response = change_call(
        app, settings, "POST", "/api/auth/password/change",
        token=token,
        body={"current_password": CHANGE_CURRENT, "new_password": CHANGE_NEW},
    )
    assert response.status_code == 200
    assert calls == [ids["member"]]


def test_password_reset_calls_the_shared_revoke(monkeypatch):
    calls = []
    async def recording(request, user_id):
        calls.append(user_id)
        return True
    monkeypatch.setattr(shared_session_revoke, "revoke_after_credential_change", recording)

    db, ids = seed_reset_db()
    delivery = RecordingDelivery()
    app, _settings = build_reset_app(db, delivery=delivery)
    request_reset(app, ids["member_email"])
    token = _token_from_mail(delivery)
    response = confirm_reset(app, token)
    assert response.status_code == 200
    assert calls == [ids["member"]]
