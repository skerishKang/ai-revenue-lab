"""Password find (#7679): the #7606 mailed proof, widened to a live credential.

Real migration SQLite, the signed RPC and a fake delivery, on the harness of
``test_email_recovery_7606``. Nothing here sends mail or reaches a network.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import re

import pytest

from app.config import Settings
from app.history import D1HistoryStore, _password_user_id
from app.password_auth import hash_password, verify_password
from app.password_recovery import is_recovered_password_user
from test_email_recovery_7606 import ACCOUNT, EMAIL, PASSWORD, SOURCE, build, rpc

OLD_PASSWORD = "existing-password-7679"
START = 1_795_000_000


def build_find(*, find=True):
    app, db, mail = build()
    object.__setattr__(app.state.settings, "password_find_enabled", find)
    clock = [START]
    app.state.password_recovery_clock = lambda: clock[0]
    return app, db, mail, clock


def live(db, email=EMAIL):
    """One live email credential; returns its local id and creation time."""
    store = D1HistoryStore(db)
    asyncio.run(store.register_password_user(email, email, "User", hash_password(OLD_PASSWORD)))
    credential = asyncio.run(store.find_password_credential(email))
    return credential.user.id, credential.created_at


def ask(app, epoch, *, email=EMAIL, source=SOURCE, account=ACCOUNT, mode="reset"):
    payload = {"email": email, "source_digest": source, "account_id": account, "credential_epoch": epoch}
    if mode is not None:
        payload["mode"] = mode
    return rpc(app, "request", payload)


def finish(app, token, epoch, *, password=PASSWORD, account=ACCOUNT):
    return rpc(app, "complete", {"token": token, "new_password": password,
                                 "account_id": account, "credential_epoch": epoch})


def tokens(db):
    return [dict(row) for row in db.connection.execute("SELECT * FROM password_recovery_tokens")]


def credential_of(db, email=EMAIL):
    return asyncio.run(D1HistoryStore(db).find_password_credential(email))


def test_status_names_a_live_credential_only_while_the_switch_is_on():
    app, db, _, _ = build_find(find=False)
    live(db)
    # Switch off: the answer is the #7606 answer, byte for byte.
    assert rpc(app, "status", {"email": EMAIL}).content == b'{"ok":true,"available":false}'
    object.__setattr__(app.state.settings, "password_find_enabled", True)
    assert rpc(app, "status", {"email": EMAIL}).json() == {"ok": True, "available": False, "present": True}
    assert rpc(app, "status", {"email": "nobody@example.test"}).json() == {
        "ok": True, "available": True, "present": False}


def test_a_google_only_account_is_never_a_password_find_target():
    app, db, mail, _ = build_find()
    db.connection.execute(
        "INSERT INTO users(id,auth_provider,provider_subject,email,display_name,picture_url,created_at,updated_at) "
        "VALUES ('usr_google','google','google_subject',?,'User','','2026-10-01T10:00:00+00:00','2026-10-01T10:00:00+00:00')",
        (EMAIL,))
    assert rpc(app, "status", {"email": EMAIL}).json() == {"ok": True, "available": False, "present": False}
    assert ask(app, "2026-10-01T10:00:00+00:00").content == b'{"ok":true}'
    assert mail.messages == [] and tokens(db) == []


def test_request_binds_a_hashed_15_minute_token_to_the_live_credential_and_mails_the_link():
    app, db, mail, _ = build_find()
    user_id, epoch = live(db)
    assert ask(app, epoch).content == b'{"ok":true}'
    assert len(mail.messages) == 1 and mail.messages[0]["to"] == EMAIL
    token = mail.token()
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", token)
    assert "https://auth.padiem.net/password/recovery/confirm#token=" + token in mail.messages[0]["text"]
    (row,) = tokens(db)
    assert re.fullmatch(r"[0-9a-f]{64}", row["token_digest"]) and token not in repr(row)
    assert row["expires_at"] - row["issued_at"] == 900
    assert (row["user_id"], row["email"], row["account_id"], row["credential_epoch"]) == (user_id, EMAIL, ACCOUNT, epoch)
    assert row["consumed_at"] is None
    assert rpc(app, "inspect", {"token": token}).json() == {
        "ok": True, "email": EMAIL, "account_id": ACCOUNT, "credential_epoch": epoch,
        "mode": "reset", "product_user_id": user_id,
    }


@pytest.mark.parametrize("case", ["unknown", "recreated", "limited", "delivery_down"])
def test_request_answers_are_byte_identical_whatever_happens(case):
    app, db, mail, clock = build_find()
    _, epoch = live(db)
    baseline = ask(app, epoch)
    assert len(mail.messages) == 1
    clock[0] += 61
    if case == "unknown":
        answer = ask(app, epoch, email="nobody@example.test", source="b" * 64)
    elif case == "recreated":
        # The address has a credential, created again after auth linked the account.
        answer = ask(app, "2020-01-01T00:00:00+00:00", source="b" * 64)
    elif case == "limited":
        clock[0] -= 60  # inside the per-address interval
        answer = ask(app, epoch, source="b" * 64)
    else:
        mail.result = False
        answer = ask(app, epoch, source="b" * 64)
    assert (answer.status_code, answer.content) == (baseline.status_code, baseline.content) == (200, b'{"ok":true}')
    # Every header but the per-request trace id.
    plain = lambda response: {k: v for k, v in response.headers.items() if k != "x-request-id"}
    assert plain(answer) == plain(baseline)
    assert len(mail.messages) == (2 if case == "delivery_down" else 1)
    assert len(tokens(db)) == (2 if case == "delivery_down" else 1)


@pytest.mark.parametrize("scope", ["email", "source"])
def test_the_recovery_request_limits_also_bound_password_find(scope):
    app, db, mail, clock = build_find()
    clock[0] = 1_795_046_400  # UTC midnight
    _, epoch = live(db)
    others = [live(db, f"person{i}@example.test")[1] for i in range(1, 7)] if scope == "source" else []

    def attempt(i):
        if scope == "email":
            return ask(app, epoch, source=f"{i:064x}")
        return ask(app, others[i - 1] if i else epoch, email=f"person{i}@example.test" if i else EMAIL)

    attempt(0)
    attempt(1)  # inside the 60 second interval
    assert len(mail.messages) == 1
    for i in range(2, 6):
        clock[0] += 61
        attempt(i)
    assert len(mail.messages) == 5
    clock[0] += 61
    assert attempt(6).content == b'{"ok":true}'  # the sixth of the day is refused silently
    assert len(mail.messages) == 5 and len(tokens(db)) == 5


def test_completion_replaces_only_the_hash_and_keeps_the_identity():
    app, db, mail, clock = build_find()
    user_id, epoch = live(db)
    db.connection.execute("UPDATE password_credentials SET failed_attempts=4, locked_until='2999-01-01T00:00:00Z'")
    before = dict(db.connection.execute("SELECT * FROM users").fetchone())
    ask(app, epoch)
    clock[0] += 30
    answer = finish(app, mail.token(), epoch)
    assert answer.status_code == 200
    assert answer.json() == {"ok": True, "product_user_id": user_id, "account_id": ACCOUNT, "credential_epoch": epoch}
    assert user_id == _password_user_id(EMAIL)
    credential = credential_of(db)
    assert verify_password(PASSWORD, credential.password_hash)
    assert not verify_password(OLD_PASSWORD, credential.password_hash)
    assert credential.created_at == epoch, "the account stays linked with the same credential"
    row = dict(db.connection.execute("SELECT * FROM password_credentials").fetchone())
    assert (row["failed_attempts"], row["locked_until"]) == (0, None)
    assert dict(db.connection.execute("SELECT * FROM users").fetchone()) == before
    assert db.connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
    # A password change restores nothing: no consumed proof is left behind.
    assert tokens(db) == []
    assert asyncio.run(is_recovered_password_user(db, user_id)) is False


@pytest.mark.parametrize("kind", ["used", "expired", "unknown", "malformed", "other_account", "other_epoch"])
def test_refused_tokens_share_one_answer_and_change_nothing(kind):
    app, db, mail, clock = build_find()
    _, epoch = live(db)
    ask(app, epoch)
    token = mail.token()
    account, sent_epoch, expected = ACCOUNT, epoch, OLD_PASSWORD
    if kind == "used":
        assert finish(app, token, epoch, password="first-mail-proven-password").status_code == 200
        expected = "first-mail-proven-password"
    elif kind == "expired":
        clock[0] += 900
    elif kind == "unknown":
        token = "u" * 43
    elif kind == "malformed":
        token = "short"
    elif kind == "other_account":
        account = "sub_another_account_7679"
    else:
        sent_epoch = "2020-01-01T00:00:00+00:00"
    answer = finish(app, token, sent_epoch, account=account)
    reference = finish(app, "r" * 43, epoch)
    assert (answer.status_code, answer.content) == (reference.status_code, reference.content)
    assert answer.status_code == 400 and answer.json()["error"]["code"] == "password_recovery_invalid"
    assert verify_password(expected, credential_of(db).password_hash)
    if kind in {"other_account", "other_epoch"}:
        assert len(tokens(db)) == 1 and tokens(db)[0]["consumed_at"] is None, "a refused swap leaves the link open"


def test_a_newer_link_ends_every_older_one_for_the_address():
    app, db, mail, clock = build_find()
    _, epoch = live(db)
    ask(app, epoch)
    older = mail.token()
    clock[0] += 61
    ask(app, epoch, source="b" * 64)
    newer = mail.token()
    assert older != newer and len(tokens(db)) == 2
    assert finish(app, newer, epoch).status_code == 200
    assert tokens(db) == []
    assert finish(app, older, epoch, password="another-mail-proven-password").status_code == 400
    assert verify_password(PASSWORD, credential_of(db).password_hash)


def test_a_weak_password_is_refused_before_any_session_ends_and_the_link_stays_open(monkeypatch):
    from app import auth_routes
    ended = []

    async def record(request, **kwargs):
        ended.append(kwargs)
        return None

    monkeypatch.setattr(auth_routes, "end_sessions_for_credential_reset", record)
    app, db, mail, _ = build_find()
    _, epoch = live(db)
    ask(app, epoch)
    token = mail.token()
    refused = finish(app, token, epoch, password="short")
    assert refused.status_code == 400 and refused.json()["error"]["code"] == "invalid_password"
    assert ended == [] and len(tokens(db)) == 1
    assert rpc(app, "inspect", {"token": token, "new_password": "short"}).status_code == 400
    assert finish(app, token, epoch).status_code == 200
    assert ended == [{"user_id": _password_user_id(EMAIL), "account_ids": (ACCOUNT,)}]


def test_sessions_end_through_the_reset_routes_own_function_and_old_sessions_stay_out():
    from app import auth_routes
    from app.auth_validation_cache import SqliteAuthValidationCache
    assert "end_sessions_for_credential_reset(" in inspect.getsource(auth_routes.password_reset_confirm)
    app, db, mail, clock = build_find()
    user_id, epoch = live(db)
    object.__setattr__(app.state.settings, "local_verify_enabled", True)
    cache = SqliteAuthValidationCache(db, clock=lambda: clock[0])
    app.state.auth_validation_cache = cache
    asyncio.run(cache.record_allowed_session(session_id="old-sid", user_id=user_id, account_id=ACCOUNT))
    assert not asyncio.run(cache.is_revoked(session_ids=("old-sid",), account_id=ACCOUNT, user_id=user_id))
    ask(app, epoch)
    assert finish(app, mail.token(), epoch).status_code == 200
    assert asyncio.run(cache.is_revoked(session_ids=("old-sid",), account_id=ACCOUNT, user_id=user_id))
    assert asyncio.run(cache.is_revoked(session_ids=("unseen-old-sid",), account_id=ACCOUNT, user_id=user_id))
    # The person signs in again with the new password and that session works.
    asyncio.run(cache.record_allowed_session(session_id="new-sid", user_id=user_id, account_id=ACCOUNT))
    assert not asyncio.run(cache.is_revoked(session_ids=("new-sid",), account_id=ACCOUNT, user_id=user_id))


def test_a_session_that_cannot_be_ended_leaves_the_password_and_the_link_untouched(caplog):
    app, db, mail, _ = build_find()
    _, epoch = live(db)
    # Local verification is on and its revocation store is absent: fail closed.
    object.__setattr__(app.state.settings, "local_verify_enabled", True)
    if hasattr(app.state, "auth_validation_cache"):
        del app.state.auth_validation_cache
    ask(app, epoch)
    token = mail.token()
    with caplog.at_level(logging.WARNING):
        answer = finish(app, token, epoch)
    assert answer.status_code == 503
    assert answer.json()["error"]["code"] == "password_recovery_unavailable"
    assert verify_password(OLD_PASSWORD, credential_of(db).password_hash)
    assert len(tokens(db)) == 1 and tokens(db)[0]["consumed_at"] is None
    assert [r.getMessage() for r in caplog.records if r.name.endswith("password_recovery")] == [
        "password_recovery reason=session_revocation_failed"]


def test_without_local_verification_the_canonical_sessions_are_revoked_strictly():
    class Authority:
        def __init__(self):
            self.calls = []

        async def revoke_all_auth_sessions(self, **kwargs):
            self.calls.append(kwargs)

    app, db, mail, _ = build_find()
    user_id, epoch = live(db)
    object.__setattr__(app.state.settings, "local_verify_enabled", False)
    app.state.control_plane_identity_authority = object()  # predates the capability
    ask(app, epoch)
    token = mail.token()
    assert finish(app, token, epoch).status_code == 503
    assert verify_password(OLD_PASSWORD, credential_of(db).password_hash)
    authority = Authority()
    app.state.control_plane_identity_authority = authority
    assert finish(app, token, epoch).status_code == 200
    assert [call["product_user_id"] for call in authority.calls] == [user_id]
    assert verify_password(PASSWORD, credential_of(db).password_hash)


def test_the_token_never_reaches_storage_logs_or_answers(caplog):
    app, db, mail, _ = build_find()
    _, epoch = live(db)
    with caplog.at_level(logging.DEBUG):
        answers = [ask(app, epoch)]
        token = mail.token()
        answers.append(rpc(app, "inspect", {"token": token}))
        stored = "\n".join(
            repr(tuple(row)) for (name,) in db.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            for row in db.connection.execute(f'SELECT * FROM "{name}"').fetchall())
        answers.append(finish(app, token, epoch))
        answers.append(finish(app, token, epoch))
    assert token not in stored
    assert all(token not in answer.text for answer in answers)
    assert all(token not in record.getMessage() for record in caplog.records)
    assert sum(token in message["text"] for message in mail.messages) == 1, "the link is the only copy"


def test_switch_off_refuses_the_new_mode_and_stops_a_link_that_is_already_out():
    app, db, mail, _ = build_find(find=False)
    _, epoch = live(db)
    refused = ask(app, epoch)
    assert refused.status_code == 400 and mail.messages == [] and tokens(db) == []
    assert db.connection.execute("SELECT COUNT(*) FROM password_recovery_requests").fetchone()[0] == 0
    # The #7606 payload is untouched: a live address is charged and gets nothing.
    assert ask(app, epoch, mode=None).content == b'{"ok":true}'
    assert mail.messages == [] and tokens(db) == []
    object.__setattr__(app.state.settings, "password_find_enabled", True)
    assert ask(app, epoch, mode="restore", source="b" * 64).status_code == 400
    assert ask(app, epoch, account=None, source="c" * 64).status_code == 400
    app.state.password_recovery_clock = lambda: START + 61
    assert ask(app, epoch, source="d" * 64).content == b'{"ok":true}'
    token = mail.token()
    object.__setattr__(app.state.settings, "password_find_enabled", False)
    assert rpc(app, "inspect", {"token": token}).json() == {
        "ok": True, "email": EMAIL, "account_id": ACCOUNT, "credential_epoch": epoch}
    assert finish(app, token, epoch).status_code == 400
    assert verify_password(OLD_PASSWORD, credential_of(db).password_hash)


def test_switch_defaults_off_and_follows_the_recovery_switch_projection(monkeypatch):
    from app.worker_config import settings_from_worker_bindings
    monkeypatch.delenv("PADIEM_AUTH_PASSWORD_FIND_ENABLED", raising=False)
    assert Settings.from_env().password_find_enabled is False
    monkeypatch.setenv("PADIEM_AUTH_PASSWORD_FIND_ENABLED", "true")
    assert Settings.from_env().password_find_enabled is True
    assert Settings.from_values(password_find_enabled="false").password_find_enabled is False
    assert settings_from_worker_bindings({}).password_find_enabled is False
    assert settings_from_worker_bindings({"PADIEM_AUTH_PASSWORD_FIND_ENABLED": "true"}).password_find_enabled is True
    # Without the recovery switch the routes do not exist at all.
    app, db, mail = build(enabled=False)
    object.__setattr__(app.state.settings, "password_find_enabled", True)
    _, epoch = live(db)
    assert ask(app, epoch).status_code == 404 and mail.messages == []
