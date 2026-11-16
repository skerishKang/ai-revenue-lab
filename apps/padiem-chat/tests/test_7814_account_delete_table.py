"""#7814 T4 — _account_delete_impl identity segment golden table.

The helper `_account_delete_identity` returns `(response | None, values)`. Every
refusal path below must answer before any delete statement runs; the fake store
raises if `batch` is ever called on a refusal. The success path returns the
resolved values and also deletes nothing by itself.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app import account_deletion as ad


class _Statement:
    def __init__(self, db, sql):
        self.db = db
        self.sql = sql

    def bind(self, *params):
        self.params = params
        return self

    async def first(self):
        if "platform_admin_roles" in self.sql:
            if self.db.admin_error:
                raise RuntimeError("admin lookup down")
            return self.db.admin_role
        return self.db.row


class _FakeDB:
    def __init__(self, *, row=None, admin_role=None, admin_error=False):
        self.row = row
        self.admin_role = admin_role
        self.admin_error = admin_error
        self.batch_calls = 0
        self.deletes = 0

    def prepare(self, sql):
        return _Statement(self, sql)

    async def batch(self, statements):
        self.batch_calls += 1
        for statement in statements:
            if statement.sql.strip().upper().startswith("DELETE"):
                self.deletes += 1
        return []


def _request(db, *, admin_email=""):
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                account_data_db=db,
                central_admin_google_email=admin_email,
            )
        )
    )


def _body(response):
    return json.loads(bytes(response.body).decode("utf-8"))


@pytest.fixture()
def wires(monkeypatch):
    def apply(*, ready=True, user_id="usr_owner", body=None, row=None):
        monkeypatch.setattr(ad, "auth_ready", lambda request: ready)
        monkeypatch.setattr(ad, "current_user_id", lambda request: user_id)
        monkeypatch.setattr(ad, "_row_to_dict", lambda value: value)
        if row is not None:
            monkeypatch.setattr(ad, "_row_to_dict", lambda value: row)

        async def json_body(request):
            return body

        monkeypatch.setattr(ad, "_json_body", json_body)

    return apply


@pytest.mark.asyncio
async def test_not_ready_answers_without_a_store(wires):
    wires(ready=False)
    db = _FakeDB()
    resp, fields = await ad._account_delete_identity(_request(db), bookai_subject_id=None)
    assert resp.status_code == 503
    assert fields == {}
    assert db.batch_calls == 0


@pytest.mark.asyncio
async def test_missing_session_is_refused(wires):
    wires(user_id=None)
    db = _FakeDB()
    resp, _ = await ad._account_delete_identity(_request(db), bookai_subject_id=None)
    assert resp.status_code == 401
    assert _body(resp)["error"]["code"] == "authentication_required"
    assert db.batch_calls == 0


@pytest.mark.asyncio
async def test_missing_store_is_refused(wires):
    wires()
    resp, _ = await ad._account_delete_identity(_request(None), bookai_subject_id=None)
    assert resp.status_code == 503
    assert _body(resp)["error"]["code"] == "account_delete_unavailable"


@pytest.mark.asyncio
async def test_bookai_resolution_failure_is_refused(wires, monkeypatch):
    wires()
    db = _FakeDB()
    from app import bookai_account_deletion

    async def boom(request, subject_id):
        raise RuntimeError("authority down")

    monkeypatch.setattr(bookai_account_deletion, "resolve_bookai_user", boom)
    resp, _ = await ad._account_delete_identity(_request(db), bookai_subject_id="sub_bookai")
    assert resp.status_code == 503
    assert _body(resp)["error"]["code"] == "account_delete_unavailable"
    assert db.batch_calls == 0


@pytest.mark.asyncio
async def test_row_without_email_is_refused(wires):
    wires(row={"email": None, "provider_subject": None})
    db = _FakeDB()
    resp, _ = await ad._account_delete_identity(_request(db), bookai_subject_id=None)
    assert resp.status_code == 401
    assert _body(resp)["error"]["code"] == "authentication_required"
    assert db.batch_calls == 0


@pytest.mark.asyncio
async def test_wrong_body_shape_is_refused(wires):
    wires(row={"email": "owner@example.test", "provider_subject": None}, body={"email": "x"})
    db = _FakeDB()
    resp, _ = await ad._account_delete_identity(_request(db), bookai_subject_id=None)
    assert resp.status_code == 400
    assert _body(resp)["error"]["code"] == "invalid_request"
    assert db.batch_calls == 0


@pytest.mark.asyncio
async def test_mismatched_confirm_email_is_refused(wires):
    wires(row={"email": "owner@example.test", "provider_subject": None}, body={"confirm": "other@example.test"})
    db = _FakeDB()
    resp, _ = await ad._account_delete_identity(_request(db), bookai_subject_id=None)
    assert resp.status_code == 400
    assert _body(resp)["error"]["code"] == "account_delete_confirm_mismatch"
    assert db.batch_calls == 0


@pytest.mark.asyncio
async def test_central_admin_email_is_refused(wires):
    wires(row={"email": "owner@example.test", "provider_subject": None}, body={"confirm": "owner@example.test"})
    db = _FakeDB()
    resp, _ = await ad._account_delete_identity(
        _request(db, admin_email="owner@example.test"), bookai_subject_id=None
    )
    assert resp.status_code == 403
    assert _body(resp)["error"]["code"] == "account_delete_admin_blocked"
    assert db.batch_calls == 0


@pytest.mark.asyncio
async def test_admin_role_lookup_failure_is_refused(wires):
    wires(row={"email": "owner@example.test", "provider_subject": None}, body={"confirm": "owner@example.test"})
    db = _FakeDB(admin_error=True)
    resp, _ = await ad._account_delete_identity(_request(db), bookai_subject_id=None)
    assert resp.status_code == 503
    assert _body(resp)["error"]["code"] == "account_delete_unavailable"
    assert db.batch_calls == 0


@pytest.mark.asyncio
async def test_stored_platform_admin_role_is_refused(wires):
    wires(row={"email": "owner@example.test", "provider_subject": None}, body={"confirm": "owner@example.test"})
    db = _FakeDB(admin_role={"user_id": "usr_owner"})
    resp, _ = await ad._account_delete_identity(_request(db), bookai_subject_id=None)
    assert resp.status_code == 403
    assert _body(resp)["error"]["code"] == "account_delete_admin_blocked"
    assert db.batch_calls == 0


@pytest.mark.asyncio
async def test_confirmed_owner_passes_with_the_same_values_and_deletes_nothing(wires):
    wires(row={"email": "owner@example.test", "provider_subject": None}, body={"confirm": "owner@example.test"})
    db = _FakeDB()
    resp, fields = await ad._account_delete_identity(_request(db), bookai_subject_id=None)
    assert resp is None
    assert fields["db"] is db
    assert fields["user_id"] == "usr_owner"
    assert fields["row"] == {"email": "owner@example.test", "provider_subject": None}
    assert fields["email"] == "owner@example.test"
    assert db.batch_calls == 0
    assert db.deletes == 0
