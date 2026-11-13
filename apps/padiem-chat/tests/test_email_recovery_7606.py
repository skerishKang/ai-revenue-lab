"""Mail-proven recovery: real migration SQLite, signed RPC and fake delivery."""
from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import time
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.d1_sqlite import SqliteD1
from app.history import D1HistoryStore, _password_user_id
from app.main import create_app
from app.password_auth import hash_password, verify_password
from test_password_rpc_261106 import proof_headers

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://chat.example.test"
SECRET = "email-recovery-rpc-test-secret-00000000"
EMAIL = "returning@example.test"
ACCOUNT = "sub_existing_account_7606"
EPOCH = "2026-10-01T10:00:00+00:00"
PASSWORD = "new-mail-proven-password-7606"
SOURCE = "a" * 64
PREFIX = "/internal/password-recovery/"


class Mail:
    def __init__(self):
        self.messages = []
        self.result = True

    async def send(self, **message):
        self.messages.append(message)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def token(self):
        return self.messages[-1]["text"].split("#token=", 1)[1].split()[0]


def build(*, enabled=True, before_recovery_migration=False):
    connection = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    for path in sorted((ROOT / "migrations").glob("*.sql")):
        if before_recovery_migration and path.name.startswith("114_"):
            continue
        connection.executescript(path.read_text(encoding="utf-8"))
    db = SqliteD1(connection)
    settings = Settings.from_values(
        runtime_mode="mock", auth_mode="password", public_base_url=BASE,
        session_secret="email-recovery-test-session-secret-00000000",
        password_rpc_secret=SECRET,
    )
    # Also works against the pre-change Settings, making the baseline failure
    # the missing real route rather than an unknown constructor argument.
    object.__setattr__(settings, "email_recovery_enabled", enabled)
    delivery = Mail()
    app = create_app(settings=settings, d1_binding=db, history_store=D1HistoryStore(db),
                     password_reset_delivery=delivery)
    return app, db, delivery


async def send(app, action, payload, *, secret=SECRET, headers=None):
    path = PREFIX + action
    body = json.dumps(payload, separators=(",", ":")).encode()
    signed = proof_headers(secret, path, body) if headers is None else headers
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client:
        return await client.post(path, content=body, headers=signed)


def rpc(app, action, payload, **kwargs):
    return asyncio.run(send(app, action, payload, **kwargs))


def issue(app, *, email=EMAIL, source=SOURCE, account=ACCOUNT, epoch=EPOCH):
    return rpc(app, "request", {"email": email, "source_digest": source,
        "account_id": account, "credential_epoch": epoch})


def complete(app, token, *, password=PASSWORD, account=ACCOUNT, epoch=EPOCH):
    return rpc(app, "complete", {"token": token, "new_password": password,
        "account_id": account, "credential_epoch": epoch})


def test_signed_status_reaches_new_route_and_reports_only_chat_absence():
    app, _, _ = build()
    response = rpc(app, "status", {"email": EMAIL})
    assert response.status_code == 200
    assert response.json() == {"ok": True, "available": True}


def test_token_hash_only_900_seconds_and_same_logical_credential_restore():
    app, db, mail = build()
    clock = [1_795_000_000]
    app.state.password_recovery_clock = lambda: clock[0]
    assert issue(app).content == b'{"ok":true}'
    token = mail.token()
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", token)
    assert "https://auth.padiem.net/password/recovery/confirm#token=" in mail.messages[0]["text"]
    row = dict(db.connection.execute("SELECT * FROM password_recovery_tokens").fetchone())
    assert re.fullmatch(r"[0-9a-f]{64}", row["token_digest"])
    assert token not in repr(row)
    assert row["expires_at"] - row["issued_at"] == 900
    assert row["account_id"] == ACCOUNT and row["credential_epoch"] == EPOCH
    assert rpc(app, "inspect", {"token": token}).json() == {
        "ok": True, "email": EMAIL, "account_id": ACCOUNT, "credential_epoch": EPOCH,
    }
    result = complete(app, token).json()
    assert result == {"ok": True, "product_user_id": row["user_id"], "account_id": ACCOUNT, "credential_epoch": EPOCH}
    assert re.fullmatch(r"usr_[0-9a-f]{32}", result["product_user_id"])
    assert result["product_user_id"] != _password_user_id(EMAIL)
    credential = asyncio.run(D1HistoryStore(db).find_password_credential(EMAIL))
    assert verify_password(PASSWORD, credential.password_hash)
    assert credential.created_at == EPOCH
    assert db.connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
    assert db.connection.execute("SELECT account_id FROM password_recovery_tokens").fetchone()[0] == ACCOUNT
    assert db.connection.execute("SELECT consumed_at FROM password_recovery_tokens").fetchone()[0] == clock[0]


@pytest.mark.parametrize("kind", ["expired", "used", "unknown", "malformed"])
def test_expired_consumed_and_unknown_tokens_have_identical_response(kind):
    app, db, mail = build()
    issue(app)
    token = mail.token()
    if kind == "expired":
        app.state.password_recovery_clock = lambda: 9_999_999_999
    elif kind == "used":
        assert complete(app, token).status_code == 200
    elif kind == "unknown":
        token = "z" * 43
    else:
        token = "bad"
    response = complete(app, token)
    assert response.status_code == 400
    assert response.json() == {"error": {"code": "password_recovery_invalid",
        "message": "복구 링크가 올바르지 않거나 더 이상 유효하지 않습니다."}}
    assert rpc(app, "inspect", {"token": token}).json() == {"ok": False}


def test_expiry_exact_boundary_is_refused_before_password_store():
    app, db, mail = build()
    app.state.password_recovery_clock = lambda: 1_795_000_000
    issue(app)
    app.state.password_recovery_clock = lambda: 1_795_000_900
    assert complete(app, mail.token()).status_code == 400
    assert db.connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    assert db.connection.execute("SELECT consumed_at FROM password_recovery_tokens").fetchone()[0] is None


def test_expiry_during_password_hashing_does_not_extend_lifetime(monkeypatch):
    from app import password_recovery
    app, db, mail = build()
    clock = [1_795_000_000]
    app.state.password_recovery_clock = lambda: clock[0]
    issue(app)

    async def hashing(_password):
        clock[0] += 900
        return hash_password(PASSWORD)

    monkeypatch.setattr(password_recovery, "hash_password_async", hashing)
    assert complete(app, mail.token()).status_code == 400
    assert db.connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


def test_two_simultaneous_redemptions_have_one_winner_and_one_password(monkeypatch):
    from app import password_recovery
    app, db, mail = build()
    issue(app)
    token = mail.token()

    async def race():
        entered = 0
        both = asyncio.Event()

        async def hashing(password):
            nonlocal entered
            entered += 1
            if entered == 2:
                both.set()
            await both.wait()
            return hash_password(password)

        monkeypatch.setattr(password_recovery, "hash_password_async", hashing)
        values = [PASSWORD, "second-new-password-7606"]
        responses = await asyncio.gather(*[
            send(app, "complete", {"token": token, "new_password": value,
                "account_id": ACCOUNT, "credential_epoch": EPOCH}) for value in values
        ])
        return values, responses

    values, responses = asyncio.run(race())
    assert sorted(r.status_code for r in responses) == [200, 400]
    winner = next(i for i, r in enumerate(responses) if r.status_code == 200)
    credential = asyncio.run(D1HistoryStore(db).find_password_credential(EMAIL))
    assert verify_password(values[winner], credential.password_hash)
    assert not verify_password(values[1 - winner], credential.password_hash)
    assert db.connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1


def test_failure_after_cas_and_user_insert_rolls_back_then_same_link_retries():
    app, db, mail = build()
    issue(app)
    token = mail.token()
    db.connection.execute("CREATE TRIGGER fail_recovery BEFORE INSERT ON password_credentials "
                          "BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END")
    assert complete(app, token).status_code == 503
    assert db.connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    row = db.connection.execute("SELECT consumed_at,consumed_by FROM password_recovery_tokens").fetchone()
    assert tuple(row) == (None, None)
    db.connection.execute("DROP TRIGGER fail_recovery")
    assert complete(app, token).status_code == 200


@pytest.mark.parametrize("delivery_result", [True, False, RuntimeError("synthetic"), None])
def test_delivery_and_ineligible_results_are_byte_identical(delivery_result):
    app, db, mail = build()
    mail.result = delivery_result
    if delivery_result is None:
        app.state.password_reset_delivery = None
    approved = issue(app)
    # Different input/source bypasses cooldown without changing target status.
    refused = issue(app, email="unknown@example.test", source="b" * 64, account=None, epoch=None)
    throttled = issue(app)
    assert approved.status_code == refused.status_code == throttled.status_code == 200
    assert approved.content == refused.content == throttled.content == b'{"ok":true}'
    assert db.connection.execute("SELECT COUNT(*) FROM password_recovery_tokens").fetchone()[0] == 1


def test_storage_failure_is_same_request_answer_and_logs_only_reason(caplog):
    app, db, _ = build()
    db.connection.execute("DROP TABLE password_recovery_requests")
    response = issue(app)
    assert response.status_code == 200 and response.content == b'{"ok":true}'
    recovery_logs = [r.getMessage() for r in caplog.records if r.name.endswith("password_recovery")]
    assert recovery_logs == ["password_recovery reason=request_storage_failed"]


def _existing_user(db, *, google=False):
    if google:
        db.connection.execute(
            "INSERT INTO users(id,auth_provider,provider_subject,email,display_name,picture_url,created_at,updated_at) "
            "VALUES ('usr_google','google','google_subject',?,'User','',?,?)", (EMAIL, EPOCH, EPOCH))
    else:
        asyncio.run(D1HistoryStore(db).register_password_user(EMAIL, EMAIL, "User", hash_password("existing-password")))


@pytest.mark.parametrize("google", [False, True])
def test_live_password_and_google_users_are_not_available_and_never_mailed(google):
    app, db, mail = build()
    _existing_user(db, google=google)
    assert rpc(app, "status", {"email": EMAIL}).json() == {"ok": True, "available": False}
    assert issue(app).content == b'{"ok":true}'
    assert mail.messages == []
    assert db.connection.execute("SELECT COUNT(*) FROM password_recovery_tokens").fetchone()[0] == 0


def test_live_user_created_after_issue_is_not_overwritten_or_consumed():
    app, db, mail = build()
    issue(app)
    _existing_user(db)
    assert complete(app, mail.token()).status_code == 400
    credential = asyncio.run(D1HistoryStore(db).find_password_credential(EMAIL))
    assert verify_password("existing-password", credential.password_hash)
    assert db.connection.execute("SELECT consumed_at FROM password_recovery_tokens").fetchone()[0] is None


@pytest.mark.parametrize("changed", [{"account": "sub_other"}, {"epoch": "2026-10-02T10:00:00+00:00"}])
def test_completion_must_match_auth_approved_account_and_epoch(changed):
    app, db, mail = build()
    issue(app)
    assert complete(app, mail.token(), **changed).status_code == 400
    assert db.connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


def test_auth_ineligible_decision_does_not_mint_token_or_create_user():
    app, db, mail = build()
    assert issue(app, account=None, epoch=None).content == b'{"ok":true}'
    assert mail.messages == []
    assert db.connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    assert db.connection.execute("SELECT COUNT(*) FROM password_recovery_requests").fetchone()[0] == 1


@pytest.mark.parametrize("scope", ["email", "source"])
def test_daily_budget_and_cooldown_use_reset_constants_for_each_scope(scope):
    app, db, mail = build()
    clock = [1_795_046_400]  # UTC midnight
    app.state.password_recovery_clock = lambda: clock[0]

    def attempt(i):
        return issue(app, email=EMAIL if scope == "email" else f"person{i}@example.test",
                     source=SOURCE if scope == "source" else f"{i:064x}")

    attempt(0)
    clock[0] += 59
    attempt(1)
    assert len(mail.messages) == 1
    clock[0] += 1
    attempt(1)
    for i in range(2, 6):
        clock[0] += 60
        attempt(i)
    assert len(mail.messages) == 5
    assert db.connection.execute("SELECT COUNT(*) FROM password_recovery_requests").fetchone()[0] == 5
    clock[0] = clock[0] // 86400 * 86400 + 86400
    attempt(6)
    assert len(mail.messages) == 6


def test_global_daily_budget_is_1000():
    app, db, mail = build()
    current = 1_795_000_000
    app.state.password_recovery_clock = lambda: current
    db.connection.executemany("INSERT INTO password_recovery_requests VALUES(?,?,?,?)",
        [(f"request-{i}", f"email-{i}", f"source-{i}", current) for i in range(1000)])
    assert issue(app).content == b'{"ok":true}'
    assert mail.messages == []
    assert db.connection.execute("SELECT COUNT(*) FROM password_recovery_requests").fetchone()[0] == 1000


def test_concurrent_request_admission_is_atomic():
    app, db, mail = build()

    async def race():
        return await asyncio.gather(*[send(app, "request", {"email": EMAIL, "source_digest": SOURCE,
            "account_id": ACCOUNT, "credential_epoch": EPOCH}) for _ in range(12)])

    responses = asyncio.run(race())
    assert {r.content for r in responses} == {b'{"ok":true}'}
    assert len(mail.messages) == 1
    assert db.connection.execute("SELECT COUNT(*) FROM password_recovery_requests").fetchone()[0] == 1


def test_opaque_source_and_email_are_hashed_and_not_logged(caplog):
    app, db, mail = build()
    mail.result = False
    issue(app, source="Q" * 43)
    row = dict(db.connection.execute("SELECT * FROM password_recovery_requests").fetchone())
    assert re.fullmatch(r"[0-9a-f]{64}", row["identifier_digest"])
    assert EMAIL not in repr(row)
    assert row["source_digest"] == "Q" * 43
    records = [r.getMessage() for r in caplog.records if r.name.endswith("password_recovery")]
    assert records == ["password_recovery reason=delivery_failed"]


@pytest.mark.parametrize("action,payload", [
    ("status", {"email": EMAIL}),
    ("request", {"email": EMAIL, "source_digest": SOURCE, "account_id": ACCOUNT, "credential_epoch": EPOCH}),
    ("inspect", {"token": "x" * 43}),
    ("complete", {"token": "x" * 43, "new_password": PASSWORD, "account_id": ACCOUNT, "credential_epoch": EPOCH}),
])
def test_switch_off_routes_are_404_and_no_ledger_or_mail_write(action, payload):
    app, db, mail = build(enabled=False)
    assert rpc(app, action, payload).status_code == 404
    assert db.connection.execute("SELECT COUNT(*) FROM password_rpc_service_ids").fetchone()[0] == 0
    assert mail.messages == []


def test_switch_defaults_and_host_projection(monkeypatch):
    from app.worker_config import settings_from_worker_bindings
    monkeypatch.delenv("PADIEM_AUTH_EMAIL_RECOVERY_ENABLED", raising=False)
    assert Settings.from_env().email_recovery_enabled is False
    monkeypatch.setenv("PADIEM_AUTH_EMAIL_RECOVERY_ENABLED", "true")
    assert Settings.from_env().email_recovery_enabled is True
    assert Settings.from_values(email_recovery_enabled="false").email_recovery_enabled is False
    assert settings_from_worker_bindings({}).email_recovery_enabled is False
    assert settings_from_worker_bindings({"PADIEM_AUTH_EMAIL_RECOVERY_ENABLED": "true"}).email_recovery_enabled is True


def test_unsigned_wrong_signature_expired_proof_and_replay_are_rejected():
    app, _, _ = build()
    assert rpc(app, "status", {"email": EMAIL}, headers={}).status_code == 401
    assert rpc(app, "status", {"email": EMAIL}, secret="wrong").status_code == 401
    body = json.dumps({"email": EMAIL}, separators=(",", ":")).encode()
    headers = proof_headers(SECRET, PREFIX + "status", body, at=1)
    assert rpc(app, "status", {"email": EMAIL}, headers=headers).status_code == 401
    headers = proof_headers(SECRET, PREFIX + "status", body)
    assert rpc(app, "status", {"email": EMAIL}, headers=headers).status_code == 200
    assert rpc(app, "status", {"email": EMAIL}, headers=headers).status_code == 409


def test_only_new_rpc_allows_larger_signed_envelope():
    app, _, _ = build()

    async def post(path, size):
        body = b'{"email":"returning@example.test"}' + b" " * size
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client:
            return await client.post(path, content=body, headers=proof_headers(SECRET, path, body))

    assert asyncio.run(post(PREFIX + "status", 600)).status_code == 200
    assert asyncio.run(post(PREFIX + "status", 4096)).status_code == 401
    assert asyncio.run(post("/internal/password-verify", 600)).status_code == 401


def test_password_policy_failure_keeps_link_open():
    app, db, mail = build()
    issue(app)
    assert complete(app, mail.token(), password="short").status_code == 400
    assert db.connection.execute("SELECT consumed_at FROM password_recovery_tokens").fetchone()[0] is None
    assert complete(app, mail.token()).status_code == 200


def test_inspect_checks_new_password_policy_before_auth_revokes_sessions(monkeypatch):
    from app import password_recovery
    app, db, mail = build()
    issue(app)

    async def no_hash(_password):
        raise AssertionError("inspect must not hash or write a password")

    monkeypatch.setattr(password_recovery, "hash_password_async", no_hash)
    bad = rpc(app, "inspect", {"token": mail.token(), "new_password": "short"})
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "invalid_password"
    good = rpc(app, "inspect", {"token": mail.token(), "new_password": PASSWORD})
    assert good.status_code == 200 and good.json()["account_id"] == ACCOUNT
    assert db.connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    assert db.connection.execute("SELECT consumed_at FROM password_recovery_tokens").fetchone()[0] is None


def test_recovery_ledger_is_removed_by_normal_chat_deletion_batch():
    from app.account_deletion import _delete_batch
    app, db, mail = build()
    issue(app)
    recovered = complete(app, mail.token())
    assert recovered.status_code == 200
    asyncio.run(db.batch(_delete_batch(db, recovered.json()["product_user_id"])))
    assert db.connection.execute("SELECT COUNT(*) FROM password_recovery_tokens").fetchone()[0] == 0
    assert db.connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


def test_disabled_recovery_needs_no_114_schema_for_old_registration_verification_or_deletion():
    from app.account_deletion import _delete_batch
    app, db, _ = build(enabled=False, before_recovery_migration=True)
    assert rpc(app, "status", {"email": EMAIL}).status_code == 404

    async def old_rpc(path, payload):
        body = json.dumps(payload, separators=(",", ":")).encode()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client:
            return await client.post(path, content=body, headers=proof_headers(SECRET, path, body))

    registered = asyncio.run(old_rpc("/internal/password-register", {"email": EMAIL, "password": PASSWORD, "name": "User"}))
    assert registered.status_code == 200
    verified = asyncio.run(old_rpc("/internal/password-verify", {"email": EMAIL, "password": PASSWORD}))
    assert verified.content == registered.content
    asyncio.run(db.batch(_delete_batch(db, _password_user_id(EMAIL))))
    assert db.connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


def test_recovery_allows_new_session_immediately_while_old_and_unseen_sessions_stay_revoked():
    from app.auth_validation_cache import SqliteAuthValidationCache
    app, db, mail = build()
    current = 1_795_000_000
    app.state.password_recovery_clock = lambda: current
    issue(app)
    cache = SqliteAuthValidationCache(db, clock=lambda: current)
    old_user_id = _password_user_id(EMAIL)
    asyncio.run(cache.record_revocation(user_ids=(old_user_id,), account_ids=(ACCOUNT,), permanent=True))
    # Even an old callback that recreated an allow marker after withdrawal
    # cannot revive its session once the mail-proven restoration completes.
    asyncio.run(cache.record_allowed_session(session_id="old-sid", user_id=old_user_id, account_id=ACCOUNT))
    assert asyncio.run(cache.is_revoked(session_ids=("old-sid",), account_id=ACCOUNT, user_id=old_user_id))
    recovered = complete(app, mail.token())
    assert recovered.status_code == 200
    user_id = recovered.json()["product_user_id"]
    asyncio.run(cache.record_allowed_session(session_id="new-sid", user_id=user_id, account_id=ACCOUNT))
    assert not asyncio.run(cache.is_revoked(session_ids=("new-sid",), account_id=ACCOUNT, user_id=user_id))
    assert asyncio.run(cache.is_revoked(session_ids=("old-sid",), account_id=ACCOUNT, user_id=user_id))
    assert asyncio.run(cache.is_revoked(session_ids=("unseen-old-sid",), account_id=ACCOUNT, user_id=user_id))


def test_session_marker_failure_rolls_back_entire_restoration_and_preserves_hard_deletion():
    from app.auth_validation_cache import SqliteAuthValidationCache
    app, db, mail = build()
    current = 1_795_000_000
    app.state.password_recovery_clock = lambda: current
    issue(app)
    cache = SqliteAuthValidationCache(db, clock=lambda: current)
    user_id = _password_user_id(EMAIL)
    asyncio.run(cache.record_revocation(user_ids=(user_id,), account_ids=(ACCOUNT,), permanent=True,
                                       ttl_seconds=3000))
    before = [tuple(row) for row in db.connection.execute("SELECT * FROM auth_validation_cache ORDER BY owner_id,session_hash")]
    db.connection.execute("CREATE TRIGGER fail_recovery_revision BEFORE UPDATE ON auth_validation_cache_revision "
                          "BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END")
    assert complete(app, mail.token()).status_code == 503
    assert db.connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    assert db.connection.execute("SELECT consumed_at FROM password_recovery_tokens").fetchone()[0] is None
    assert [tuple(row) for row in db.connection.execute("SELECT * FROM auth_validation_cache ORDER BY owner_id,session_hash")] == before
    db.connection.execute("DROP TRIGGER fail_recovery_revision")
    assert complete(app, mail.token()).status_code == 200
    rows = db.connection.execute("SELECT owner_id,valid_until FROM auth_validation_cache WHERE owner_id LIKE 'deny:%'").fetchall()
    assert {r[0] for r in rows} == {"deny:acc", "deny:usr", "deny:del"}
    assert next(r[1] for r in rows if r[0] == "deny:acc") == current + 3000
    assert next(r[1] for r in rows if r[0] == "deny:del") == current + 3000


def test_fresh_chat_identity_does_not_revive_sidless_cookie_even_after_switch_off(monkeypatch):
    from types import SimpleNamespace
    from app.account_deletion import _delete_batch
    from app.auth import SESSION_COOKIE, create_session_token
    from test_password_rpc_261106 import rpc as existing_rpc
    app, db, mail = build()
    _existing_user(db)
    old_id = _password_user_id(EMAIL)
    old_cookie = create_session_token(app.state.settings, old_id, now=int(time.time()) - 60)

    async def no_canonical_lookup(**_kwargs):
        raise AssertionError("the old cookie deliberately has no canonical sid")

    app.state.control_plane_identity_authority = SimpleNamespace(resolve_auth_session=no_canonical_lookup)
    monkeypatch.setattr("app.session_revocation_guard.sidless_session_cutoff_passed", lambda: False)

    async def old_cookie_status():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client:
            return await client.get("/api/conversations", headers={"Cookie": f"{SESSION_COOKIE}={old_cookie}"})

    assert asyncio.run(old_cookie_status()).status_code == 200
    asyncio.run(db.batch(_delete_batch(db, old_id)))
    assert asyncio.run(old_cookie_status()).status_code == 401
    issue(app)
    recovered = complete(app, mail.token())
    assert recovered.status_code == 200
    assert recovered.json()["product_user_id"] != old_id
    assert asyncio.run(old_cookie_status()).status_code == 401
    object.__setattr__(app.state.settings, "email_recovery_enabled", False)
    assert asyncio.run(old_cookie_status()).status_code == 401
    verified = existing_rpc(app, "/internal/password-verify", {"email": EMAIL, "password": PASSWORD}, secret=SECRET)
    assert verified.status_code == 200
    assert verified.json()["product_user_id"] == recovered.json()["product_user_id"]
    assert verified.json()["credential_epoch"] == EPOCH


def test_consumed_proof_preserves_canonical_admin_target_after_30_days_without_granting_role():
    from app.platform_admin_roles import D1PlatformAdminRoleStore
    from app.password_recovery import is_recovered_password_user
    app, db, mail = build()
    clock = [1_795_000_000]
    app.state.password_recovery_clock = lambda: clock[0]
    issue(app)
    recovered = complete(app, mail.token())
    assert recovered.status_code == 200
    user_id = recovered.json()["product_user_id"]
    roles = D1PlatformAdminRoleStore(db)
    assert asyncio.run(roles._canonical_user(user_id)) is not None
    assert asyncio.run(roles.role_for(user_id)) is None
    assert asyncio.run(is_recovered_password_user(db, user_id, account_id=ACCOUNT))
    assert not asyncio.run(is_recovered_password_user(db, user_id, account_id="sub_other"))
    clock[0] += 31 * 86400
    issue(app, email="other@example.test", account=None, epoch=None)
    assert db.connection.execute("SELECT COUNT(*) FROM password_recovery_tokens WHERE consumed_at IS NOT NULL").fetchone()[0] == 1
    assert asyncio.run(roles._canonical_user(user_id)) is not None
    assert asyncio.run(roles.role_for(user_id)) is None
    # A current credential cannot borrow another generation's proof.
    db.connection.execute("UPDATE password_credentials SET created_at=? WHERE user_id=?",
                          ("2026-10-02T10:00:00+00:00", user_id))
    assert asyncio.run(roles._canonical_user(user_id)) is None


def test_deletion_also_removes_unconsumed_sibling_tokens_with_different_fresh_ids():
    from app.account_deletion import _delete_batch
    app, db, mail = build()
    clock = [1_795_000_000]
    app.state.password_recovery_clock = lambda: clock[0]
    issue(app)
    first = mail.token()
    clock[0] += 60
    issue(app)
    assert db.connection.execute("SELECT COUNT(DISTINCT user_id) FROM password_recovery_tokens").fetchone()[0] == 2
    recovered = complete(app, first)
    assert recovered.status_code == 200
    asyncio.run(db.batch(_delete_batch(db, recovered.json()["product_user_id"])))
    assert db.connection.execute("SELECT COUNT(*) FROM password_recovery_tokens").fetchone()[0] == 0


def test_deleting_another_google_user_with_same_email_preserves_consumed_proof():
    from app.account_deletion import _delete_batch
    from app.password_recovery import is_recovered_password_user
    app, db, mail = build()
    issue(app)
    recovered = complete(app, mail.token())
    assert recovered.status_code == 200
    user_id = recovered.json()["product_user_id"]
    # users.email is not unique: a separate Google identity can later carry
    # the same address without owning this password credential/provenance.
    google_id = "usr_" + "f" * 32
    db.connection.execute(
        "INSERT INTO users(id,auth_provider,provider_subject,email,display_name,picture_url,created_at,updated_at) "
        "VALUES(?,'google','separate-google-subject',?,'User','',?,?)",
        (google_id, EMAIL, EPOCH, EPOCH),
    )
    asyncio.run(db.batch(_delete_batch(db, google_id)))
    assert asyncio.run(is_recovered_password_user(db, user_id, account_id=ACCOUNT))
