"""In-process withdrawal tests; no listening server, browser or real accounts."""
from __future__ import annotations

import ast
import asyncio
import hashlib
import hmac
import json
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.bookai_account_deletion import DELETE_PATH, install_bookai_account_deletion_route
from test_account_deletion_261103 import (
    BASE, DELETER_EMAIL, CanonicalAuthority, _bookai_rows, _seed_bookai,
    build_app, call, seed_db, token_for,
)

SUBJECT = "sub_withdrawal_fixture"
OTHER = "sub_withdrawal_other_fixture"
SECRET = "synthetic-bookai-delete-secret-no-real-value"
SOURCE = Path(__file__).resolve().parents[3] / "packages/padiem-control-plane/identity_authority_worker.py"


def reviewed_products(name):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.AnnAssign) and n.target.id == name)
    return frozenset(ast.literal_eval(node.value.args[0]))


class ReviewedAuthority(CanonicalAuthority):
    """Capability modes, with the actual reviewed registration/session boundary."""
    def __init__(self, *, removal_open=True):
        super().__init__()
        self.removal_open = removal_open
        self.validated = []

    async def list_active_product_links_for_subject(self, *, canonical_subject_id):
        if canonical_subject_id != SUBJECT:
            raise ValueError("wrong_owner")
        return await super().list_active_product_links_for_subject(canonical_subject_id=canonical_subject_id)

    async def revoke_auth_session(self, *, product_id, session_id):
        if product_id not in reviewed_products("_ALLOWED_PRODUCTS") - reviewed_products("_LINK_ONLY_PRODUCTS"):
            raise ValueError("product_mismatch")
        return await super().revoke_auth_session(product_id=product_id, session_id=session_id)

    async def remove_product_link(self, *, validate_only=False, **kwargs):
        product = kwargs["product_id"]
        allowed = reviewed_products("_ALLOWED_PRODUCTS")
        if not self.removal_open:
            allowed -= reviewed_products("_LINK_ONLY_PRODUCTS")
        if product not in allowed or kwargs["canonical_subject_id"] != SUBJECT:
            raise ValueError("product_mismatch")
        if validate_only:
            if not self.removal_open:
                raise ValueError("unknown_field")
            assert any(link["product_id"] == product and
                       link["product_user_id"] == kwargs["product_user_id"] for link in self.links)
            self.validated.append(product)
            return {"ok": True, "removable": True}
        return await super().remove_product_link(**kwargs)


def fixture(*, mixed=False, bookai_link=True, removal_open=True):
    db, accounts = seed_db()
    authority = ReviewedAuthority(removal_open=removal_open)
    if mixed:
        uid = accounts["deleter"]
        db.conn.execute("UPDATE users SET provider_subject=? WHERE id=?", ("shared:" + SUBJECT, uid))
        authority.links.append({"product_id": "b62", "product_user_id": uid, "state": "active"})
    if bookai_link:
        authority.links.append({"product_id": "b61", "product_user_id": "usr_bookai_fixture", "state": "active"})
    _seed_bookai(db, SUBJECT, "owned-record")
    _seed_bookai(db, OTHER, "other-record")
    events = []

    async def transport(**kwargs):
        path = kwargs["path"]
        events.append((path, _bookai_rows(db, SUBJECT)))
        result = {"ok": True, "deleted": True}
        if path.endswith("/prepare"):
            result = {"ok": True, "prepared": True, "revoked_sessions": 1}
        return SimpleNamespace(status_code=200, json=lambda: result)

    app, settings = build_app(db, authority=authority, rpc_transport=transport)
    install_bookai_account_deletion_route(app, env={"BOOKAI_COM2_SYNC_SECRET": SECRET})
    return db, accounts, app, settings, authority, events


def signed_call(app, *, subject=SUBJECT, changes=None, request_id=None, bad_signature=False):
    now = int(time.time())
    payload = {"confirm": True, "session_id": "fixture-live-session", "expires_at": now + 900,
               "request_id": request_id or str(uuid.uuid4())}
    payload.update(changes or {})
    body = json.dumps(payload, separators=(",", ":")).encode()
    canonical = "\n".join(("POST", DELETE_PATH, str(now), subject, hashlib.sha256(body).hexdigest()))
    signature = hmac.new(SECRET.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    headers = {"content-type": "application/json", "x-bookai-subject": subject,
               "x-bookai-timestamp": str(now), "x-bookai-signature": "0" * 64 if bad_signature else signature}

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=BASE) as client:
            return await client.post(DELETE_PATH, content=body, headers=headers)
    return asyncio.run(run())


@pytest.mark.parametrize("mixed,bookai_link", [(False, True), (True, True), (True, False)])
def test_bookai_entry_uses_existing_engine_without_chat_cookie(mixed, bookai_link):
    db, accounts, app, _, authority, events = fixture(mixed=mixed, bookai_link=bookai_link)
    before_users = db.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    response = signed_call(app)
    assert response.status_code == 200, response.text
    assert response.json()["common_account_deleted"] is True
    assert _bookai_rows(db, SUBJECT) == 0 and _bookai_rows(db, OTHER) == 1
    assert not authority.links
    assert events == [("/internal/account-delete/prepare", 1), ("/internal/account-delete/complete", 0)]
    assert db.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == before_users - int(mixed)
    assert db.conn.execute("SELECT COUNT(*) FROM auth_validation_cache WHERE owner_id='deny:del'").fetchone()[0] >= 1


@pytest.mark.parametrize("entry", ["bookai", "chat"])
@pytest.mark.parametrize("removal_open", [False, True])
def test_bookai_first_then_chat_removal_capability_precedes_data_mutation(entry, removal_open):
    db, accounts, app, settings, authority, events = fixture(mixed=True, removal_open=removal_open)
    response = signed_call(app) if entry == "bookai" else call(
        app, settings, "POST", "/api/account/shared-delete", origin=BASE,
        token=token_for(settings, accounts["deleter"]), body={"confirm": DELETER_EMAIL})
    assert response.status_code == (200 if removal_open else 503), response.text
    assert _bookai_rows(db, SUBJECT) == (0 if removal_open else 1)
    if not removal_open:
        assert not events and not authority.removed and not authority.revoked
        assert db.conn.execute("SELECT id FROM users WHERE id=?", (accounts["deleter"],)).fetchone()
        assert not db.conn.execute("SELECT 1 FROM auth_validation_cache WHERE owner_id='deny:del'").fetchone()


def test_prepare_failure_preserves_bookai_and_chat_data():
    db, accounts, app, _, authority, _ = fixture(mixed=True)
    async def fail(**kwargs):
        return SimpleNamespace(status_code=503, json=lambda: {})
    app.state.account_delete_rpc_transport = fail
    assert signed_call(app).status_code == 503
    assert _bookai_rows(db, SUBJECT) == 1 and not authority.removed
    assert db.conn.execute("SELECT id FROM users WHERE id=?", (accounts["deleter"],)).fetchone()


def test_complete_failure_records_existing_pending_retry_and_success():
    db, _, app, _, _, events = fixture()
    original = app.state.account_delete_rpc_transport
    async def fail_finish(**kwargs):
        if kwargs["path"].endswith("/complete"):
            return SimpleNamespace(status_code=503, json=lambda: {})
        return await original(**kwargs)
    app.state.account_delete_rpc_transport = fail_finish
    response = signed_call(app)
    assert response.status_code == 200 and response.json()["cleanup"] == {"complete": False, "pending": 1}
    assert "공통 로그인" in response.json()["message"]
    assert db.conn.execute("SELECT 1 FROM account_deletion_cleanup_pending WHERE kind='shared_account_complete'").fetchone()
    assert not any(path.endswith("/abort") for path, _ in events)


@pytest.mark.parametrize("changes", [{"confirm": False}, {"expires_at": 1}, {"expires_at": True},
                                    {"session_id": ""}, {"request_id": "invalid"}, {"unexpected": "value"}])
def test_signed_body_is_closed_and_live(changes):
    db, _, app, _, authority, _ = fixture()
    assert signed_call(app, changes=changes).status_code in {400, 401}
    assert _bookai_rows(db, SUBJECT) == 1 and not authority.removed


def test_bad_signature_wrong_owner_and_replay_are_rejected():
    db, _, app, _, _, _ = fixture(removal_open=False)
    assert signed_call(app, bad_signature=True).status_code == 401
    assert signed_call(app, subject=OTHER).status_code == 503
    request_id = str(uuid.uuid4())
    assert signed_call(app, request_id=request_id).status_code == 503
    assert signed_call(app, request_id=request_id).status_code == 409
    assert _bookai_rows(db, SUBJECT) == 1


@pytest.mark.parametrize("central", [False, True])
def test_bookai_entry_cannot_bypass_chat_admin_protection(central):
    db, accounts, app, _, authority, events = fixture(mixed=True)
    uid = accounts["deleter"]
    if central:
        app.state.central_admin_google_email = DELETER_EMAIL
    else:
        db.conn.execute("INSERT INTO platform_admin_roles(user_id,role,granted_by,created_at,updated_at) "
                        "VALUES(?, 'ADMIN', 'fixture', '2026-11-14', '2026-11-14')", (uid,))
    assert signed_call(app).status_code == 403
    assert _bookai_rows(db, SUBJECT) == 1 and not events and not authority.removed


def test_unknown_product_and_conflicting_user_mapping_stop_before_deletion():
    for mode in ("unknown", "mismatch"):
        db, accounts, app, _, authority, events = fixture(mixed=True)
        if mode == "unknown":
            authority.links.append({"product_id": "unreviewed", "product_user_id": "usr_unknown", "state": "active"})
        else:
            db.conn.execute("UPDATE users SET provider_subject=? WHERE id=?", ("shared:" + OTHER, accounts["deleter"]))
        assert signed_call(app).status_code == 503
        assert _bookai_rows(db, SUBJECT) == 1 and not events and not authority.removed


@pytest.mark.parametrize("local_verify", [False, True])
def test_chat_only_delete_leaves_remaining_bookai_account_usable(monkeypatch, local_verify):
    from app.auth_validation_cache import account_deletion_allowed_sql, SqliteAuthValidationCache
    db, accounts, app, settings, authority, events = fixture(mixed=True)
    monkeypatch.setattr("app.config.session_local_verify_enabled", lambda settings: local_verify)
    app.state.auth_validation_cache = SqliteAuthValidationCache(db)
    response = call(app, settings, "POST", "/api/account/delete", origin=BASE,
                    token=token_for(settings, accounts["deleter"]), body={"confirm": DELETER_EMAIL})
    assert response.status_code == 200 and response.json()["common_account_deleted"] is False
    assert [link["product_id"] for link in authority.links] == ["b61"]
    assert not events
    allowed, values = account_deletion_allowed_sql(SUBJECT)
    assert db.conn.execute("SELECT " + allowed, values).fetchone()[0] == 1


@pytest.mark.parametrize("result", [{"ok": True, "removable": 1}, {"ok": 1, "removable": True},
                                   {"ok": True, "removable": True, "extra": True}, {"ok": True}])
def test_preflight_requires_exact_boolean_success_before_any_deletion(result):
    db, _, app, _, authority, events = fixture()
    async def malformed(**kwargs):
        return result
    authority.remove_product_link = malformed
    assert signed_call(app).status_code == 503
    assert _bookai_rows(db, SUBJECT) == 1 and not events


@pytest.mark.parametrize("result,valid", [({"ok": True, "removable": True}, True),
                                         ({"ok": True, "removable": 1}, False),
                                         ({"ok": True, "removed": True}, False)])
def test_worker_adapter_preflight_preserves_closed_wire_and_boolean_types(result, valid):
    from app.control_plane_identity import IdentityBridgeError
    from app.control_plane_identity_worker import CloudflareControlPlaneIdentityAuthority
    seen = []
    async def rpc(method, payload):
        seen.append((method, payload))
        return result
    adapter = SimpleNamespace(_rpc_envelope=rpc)
    async def run():
        return await CloudflareControlPlaneIdentityAuthority.remove_product_link(
            adapter, product_id="b61", product_user_id="usr_fixture", canonical_subject_id=SUBJECT,
            validate_only=True)
    if valid:
        assert asyncio.run(run()) == {"ok": True, "removable": True}
    else:
        with pytest.raises(IdentityBridgeError):
            asyncio.run(run())
    assert seen[0][0] == "remove_product_link"
    assert seen[0][1] == {"product_id": "b61", "product_user_id": "usr_fixture", "canonical_subject_id": SUBJECT,
                          "account_deletion_operation_id": None, "validate_only": True}


def test_slow_signed_body_cannot_outlive_the_signature_window():
    db, _, app, _, authority, events = fixture()
    now = int(time.time())
    clock = [now]
    install_bookai_account_deletion_route(app, env={"BOOKAI_COM2_SYNC_SECRET": SECRET}, clock=lambda: clock[0])
    body = json.dumps({"confirm": True, "session_id": "fixture", "expires_at": now + 900,
                       "request_id": str(uuid.uuid4())}).encode()
    wire = "\n".join(("POST", DELETE_PATH, str(now), SUBJECT, hashlib.sha256(body).hexdigest()))
    signature = hmac.new(SECRET.encode(), wire.encode(), hashlib.sha256).hexdigest()
    async def stream():
        yield body[:1]
        clock[0] += 301
        yield body[1:]
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=BASE) as client:
            return await client.post(DELETE_PATH, content=stream(), headers={
                "content-type": "application/json", "x-bookai-subject": SUBJECT,
                "x-bookai-timestamp": str(now), "x-bookai-signature": signature})
    assert asyncio.run(run()).status_code == 401
    assert _bookai_rows(db, SUBJECT) == 1 and not authority.removed and not events


def test_concurrent_last_link_removal_keeps_unprepared_completion_pending():
    db, accounts, app, settings, authority, events = fixture(mixed=True)
    async def concurrently_removed(**kwargs):
        assert kwargs["product_id"] in reviewed_products("_ALLOWED_PRODUCTS")
        assert kwargs["canonical_subject_id"] == SUBJECT
        assert kwargs["account_deletion_operation_id"] is None
        authority.links.clear()
        return {"removed": False, "common_account_deleted": True, "already_deleted": True}
    authority.remove_product_link = concurrently_removed
    response = call(app, settings, "POST", "/api/account/delete", origin=BASE,
                    token=token_for(settings, accounts["deleter"]), body={"confirm": DELETER_EMAIL})
    assert response.status_code == 200
    assert response.json()["common_account_deleted"] is True
    assert response.json()["cleanup"]["pending"] >= 1
    assert db.conn.execute("SELECT 1 FROM account_deletion_cleanup_pending WHERE kind='shared_account_complete'").fetchone()
    assert not events
