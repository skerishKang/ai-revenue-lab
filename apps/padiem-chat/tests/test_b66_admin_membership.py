"""SQLite exercise of B66 durable admin policy, identity separation, signup trigger."""
import asyncio
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.b66_member_admin import D1B66MemberAdminStore, MemberConflict
from app.history import _password_user_id, _user_id

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "037_b66_admin_memberships.sql"


class Statement:
    def __init__(self, db, sql, args=()):
        self.db, self.sql, self.args = db, sql, args

    def bind(self, *args):
        return Statement(self.db, self.sql, args)

    async def first(self):
        row = self.db.conn.execute(self.sql, self.args).fetchone()
        return dict(row) if row else None

    async def run(self):
        cursor = self.db.conn.execute(self.sql, self.args)
        return SimpleNamespace(
            results=[dict(row) for row in cursor.fetchall()],
            meta={"changes": cursor.rowcount},
        )


class SqliteD1:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row

    def prepare(self, sql):
        return Statement(self, sql)

    async def batch(self, statements):
        with self.conn:
            return [await stmt.run() for stmt in statements]


def seed_db():
    db = SqliteD1()
    db.conn.executescript("""
        CREATE TABLE users(
            id TEXT PRIMARY KEY, auth_provider TEXT NOT NULL,
            provider_subject TEXT NOT NULL,email TEXT NOT NULL,
            display_name TEXT NOT NULL,picture_url TEXT NOT NULL,
            created_at TEXT NOT NULL,updated_at TEXT NOT NULL
        );
        CREATE TABLE password_credentials(user_id TEXT PRIMARY KEY, username TEXT);
    """)
    admin = _user_id("google-subject-real")
    legacy = _user_id("google-subject-cgi")
    fake = _password_user_id("fake-admin")
    for uid, subj, email in [
        (admin, "google-subject-real", "admin@example.test"),
        (legacy, "google-subject-cgi", "cgi1003@cgi1003.test"),
        (fake, "password:fake-admin", "admin@example.test"),
    ]:
        db.conn.execute(
            "INSERT INTO users VALUES (?,?,?,?,?,?,?,?)",
            (uid, "google", subj, email, "QA user", "", "2026-10-01T00:00:00Z", "2026-10-01T00:00:00Z")
        )
    db.conn.execute("INSERT INTO password_credentials VALUES (?,?)", (fake,"fake-admin"))
    db.conn.executescript(MIGRATION.read_text(encoding="utf-8"))
    return db, admin, legacy, fake


@pytest.mark.asyncio
async def test_admin_requires_real_google_subject_not_email_only():
    db, admin, legacy, fake = seed_db()
    store = D1B66MemberAdminStore(db, admin_email="admin@example.test")
    assert await store.is_google_admin(admin) is True
    assert await store.is_google_admin(fake) is False
    assert await store.is_google_admin(legacy) is False
    assert await store.is_google_admin("usr_" + "f" * 32) is False
    # A row whose id does not hash from Google subject cannot gain admin.
    db.conn.execute("UPDATE users SET provider_subject=? WHERE id=?", ("changed-subject",admin))
    assert await store.is_google_admin(admin) is False


@pytest.mark.asyncio
async def test_existing_members_remain_approved_new_registrations_are_pending():
    db, admin, legacy, fake = seed_db()
    store = D1B66MemberAdminStore(db, admin_email="admin@example.test")
    assert (await store.access_for_user(legacy))["status"] == "approved"
    new_id = _user_id("new-google")
    db.conn.execute(
        "INSERT INTO users VALUES (?,?,?,?,?,?,?,?)",
        (new_id, "google", "new-google", "new@test.invalid", "New", "", "2026-10-11Z", "2026-10-11Z")
    )
    assert (await store.access_for_user(new_id))["status"] == "pending"
    assert (await store.runtime_access(new_id))["model_ids"] == []
    assert await store.undelivered_signups() == 1
    assert (await store.count_members())["pending"] == 1


@pytest.mark.asyncio
async def test_review_grants_version_and_audit():
    db, admin, legacy, fake = seed_db()
    store = D1B66MemberAdminStore(db, admin_email="admin@example.test")
    result = await store.set_access(
        actor_id=admin, user_id=legacy, status="approved",
        tier="PRO", expected_revision=0,
    )
    assert result == {"status":"approved","tier":"PRO","revision":1}
    row = db.conn.execute("SELECT * FROM b66_membership_audit WHERE user_id=?", (legacy,)).fetchone()
    assert row["actor_user_id"] == admin
    assert row["previous_tier"] == "FREE"
    assert row["current_tier"] == "PRO"
    with pytest.raises(MemberConflict):
        await store.set_access(actor_id=admin,user_id=legacy,status="suspended",
                               tier="PRO",expected_revision=0)


@pytest.mark.asyncio
async def test_model_policy_fail_closed_and_registered_routes_only():
    db, admin, legacy, fake = seed_db()
    store = D1B66MemberAdminStore(db, admin_email="admin@example.test")
    registry = {"google/gemini-3.5-flash-lite","deepseek/deepseek-chat"}
    tiers = {"FREE":["google/gemini-3.5-flash-lite"],
             "PLUS":["google/gemini-3.5-flash-lite","deepseek/deepseek-chat"],
             "PRO":["deepseek/deepseek-chat"],"MAX":[]}
    with pytest.raises(ValueError):
        wrong = dict(tiers, PRO=["unregistered/router"])
        await store.set_model_policy(actor_id=admin,expected_revision=0,
                                     active=True,tiers=wrong,registered_models=registry)
    new = await store.set_model_policy(actor_id=admin,expected_revision=0,
                                       active=True,tiers=tiers,registered_models=registry)
    assert new["active"] and new["revision"] == 1
    allowed = await store.runtime_access(legacy)
    assert allowed["model_ids"] == tiers["FREE"]
    with pytest.raises(MemberConflict):
        await store.set_model_policy(actor_id=admin,expected_revision=0,
                                      active=False,tiers=tiers,registered_models=registry)
    assert db.conn.execute("SELECT COUNT(*) FROM b66_model_policy_audit").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_signup_notification_is_durable_and_channel_receipts_dedupe():
    import httpx
    from app.b66_signup_notifications import B66SignupNotifier
    db, admin, legacy, fake = seed_db()
    newcomer = _user_id("new-user-for-alert")
    db.conn.execute(
        "INSERT INTO users VALUES (?,?,?,?,?,?,?,?)",
        (newcomer,"google","new-user-for-alert","newuser@test.invalid","New",
         "", "2026-10-11Z", "2026-10-11Z")
    )
    store = D1B66MemberAdminStore(db, admin_email="admin@example.test")
    calls = []
    def handler(request):
        calls.append((request.url.host, request.url.path))
        return httpx.Response(200, json={"ok":True})
    notifier = B66SignupNotifier(
        store, telegram_bot_token="123456:" + "A"*45, telegram_chat_id="-123456",
        discord_webhook_url="https://discord.com/api/webhooks/1234567890123456789/" + "Z"*45,
        resend_api_key="re_qa_no_real_secret", email_from="notify@example.com",
        email_to="admin@example.test",
        http_transport=httpx.MockTransport(handler),
    )
    assert set(notifier.channels) == {"telegram","discord","email"}
    done = await notifier.notify_one(newcomer)
    assert done == {"sent":3,"failed":0}
    assert await store.undelivered_signups() == 0
    await notifier.notify_one(newcomer)
    assert len(calls) == 3
    assert {x[0] for x in calls} == {
        "api.telegram.org", "discord.com", "api.resend.com"
    }


@pytest.mark.asyncio
async def test_missing_alert_config_does_not_claim_delivery():
    from app.b66_signup_notifications import B66SignupNotifier
    db, admin, legacy, fake = seed_db()
    newcomer = _user_id("unsent-new-user")
    db.conn.execute(
        "INSERT INTO users VALUES (?,?,?,?,?,?,?,?)",
        (newcomer,"google","unsent-new-user","newuser@test.invalid","New",
         "", "2026-10-11Z", "2026-10-11Z")
    )
    store = D1B66MemberAdminStore(db, admin_email="admin@example.test")
    notifier = B66SignupNotifier(store)
    assert not notifier.channels
    assert await notifier.notify_one(newcomer) == {"sent":0,"failed":0}
    assert await store.undelivered_signups() == 1
