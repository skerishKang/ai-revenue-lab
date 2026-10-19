"""#5118 integrated admin roles over the existing signed session and users D1."""
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.history import _password_user_id, _user_id
from app.main import create_app
from app.platform_admin_authority import PlatformAdminAuthority
from app.platform_admin_roles import (
    AdminRoleTargetMissing,
    D1PlatformAdminRoleStore,
)

BASE = "https://chat.test"
ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "052_platform_admin_roles.sql"


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
    super_uid = _user_id("google-charlie")
    admin_uid = _user_id("google-skerish")
    member_uid = _user_id("google-member")
    password_uid = _password_user_id("skerish-password")
    forged_uid = "usr_" + "f" * 32
    rows = (
        (super_uid, "google", "google-charlie", "charliekant@gmail.com"),
        (admin_uid, "google", "google-skerish", "skerish@naver.com"),
        (member_uid, "google", "google-member", "member@example.test"),
        (password_uid, "google", "password:skerish-password", "pw@example.test"),
        (forged_uid, "google", "not-the-derived-subject", "forged@example.test"),
    )
    for uid, provider, subject, email in rows:
        db.conn.execute(
            "INSERT INTO users VALUES (?,?,?,?,?,?,?,?)",
            (
                uid, provider, subject, email, "QA user", "",
                "2026-10-01T00:00:00Z", "2026-10-01T00:00:00Z",
            ),
        )
    db.conn.execute(
        "INSERT INTO password_credentials(user_id, username) VALUES (?,?)",
        (password_uid, "skerish-password"),
    )
    db.conn.executescript(MIGRATION.read_text(encoding="utf-8"))
    return db, {
        "super": super_uid,
        "admin": admin_uid,
        "member": member_uid,
        "password": password_uid,
        "forged": forged_uid,
    }


@pytest.mark.asyncio
async def test_role_binding_requires_canonical_identity_and_records_before_after():
    db, ids = seed_db()
    store = D1PlatformAdminRoleStore(db)

    assert await store.role_for(ids["admin"]) is None

    created = await store.assign(
        actor_user_id=ids["super"], target_user_id=ids["admin"], role="ADMIN"
    )
    assert created.role == "ADMIN"
    assert created.previous_role is None
    assert await store.role_for(ids["admin"]) == "ADMIN"

    # The password compatibility row is a server-verified canonical account too.
    await store.assign(
        actor_user_id=ids["super"],
        target_user_id=ids["password"],
        role="ADMIN",
    )
    assert await store.role_for(ids["password"]) == "ADMIN"

    upgraded = await store.assign(
        actor_user_id=ids["super"],
        target_user_id=ids["admin"],
        role="SUPER_ADMIN",
    )
    assert upgraded.previous_role == "ADMIN"
    audit = db.conn.execute(
        "SELECT actor_user_id, previous_role, current_role "
        "FROM platform_admin_role_audit WHERE target_user_id=? "
        "ORDER BY id DESC LIMIT 1",
        (ids["admin"],),
    ).fetchone()
    assert tuple(audit) == (ids["super"], "ADMIN", "SUPER_ADMIN")

    with pytest.raises(AdminRoleTargetMissing):
        await store.assign(
            actor_user_id=ids["super"],
            target_user_id=ids["forged"],
            role="ADMIN",
        )
    assert await store.role_for(ids["forged"]) is None

    # A canonical row that is later rewritten can no longer exercise the role.
    db.conn.execute(
        "UPDATE users SET provider_subject=? WHERE id=?",
        ("changed-subject", ids["admin"]),
    )
    assert await store.role_for(ids["admin"]) is None
    db.conn.execute(
        "UPDATE users SET provider_subject=? WHERE id=?",
        ("google-skerish", ids["admin"]),
    )
    assert await store.role_for(ids["admin"]) == "SUPER_ADMIN"

    revoked = await store.revoke(
        actor_user_id=ids["super"], target_user_id=ids["admin"]
    )
    assert revoked.revoked is True
    assert revoked.previous_role == "SUPER_ADMIN"
    assert await store.role_for(ids["admin"]) is None
    audit = db.conn.execute(
        "SELECT previous_role, current_role FROM platform_admin_role_audit "
        "WHERE target_user_id=? ORDER BY id DESC LIMIT 1",
        (ids["admin"],),
    ).fetchone()
    assert tuple(audit) == ("SUPER_ADMIN", None)

    # Requesting a revoke twice is a truthful no-op, not a fabricated change.
    again = await store.revoke(
        actor_user_id=ids["super"], target_user_id=ids["admin"]
    )
    assert again.revoked is False


@pytest.mark.asyncio
async def test_platform_authority_matrix_keeps_customer_data_separate():
    db, ids = seed_db()
    store = D1PlatformAdminRoleStore(db)
    await store.assign(
        actor_user_id=ids["super"], target_user_id=ids["admin"], role="ADMIN"
    )
    authority = PlatformAdminAuthority(
        role_store=store,
        legacy_model_admin=CentralAdmin(ids["super"]),
        legacy_b66_admin=B66Admin(ids["member"]),
    )

    # Integrated ADMIN: platform model management and B66 policy, no customer data.
    assert await authority.role_for(ids["admin"]) == "ADMIN"
    assert await authority.is_global_model_admin(user_id=ids["admin"]) is True
    assert await authority.is_b66_platform_admin(ids["admin"]) is True
    assert await authority.is_b66_customer_admin(ids["admin"]) is False
    assert await authority.is_super_admin(user_id=ids["admin"]) is False

    # The legacy B66 owner keeps customer data and B66 policy, never central models.
    assert await authority.role_for(ids["member"]) is None
    assert await authority.is_b66_customer_admin(ids["member"]) is True
    assert await authority.is_b66_platform_admin(ids["member"]) is True
    assert await authority.is_global_model_admin(user_id=ids["member"]) is False

    # The trusted central operator stays SUPER_ADMIN without a stored row and
    # does not inherit the B66 owner's customer-data authority.
    assert await authority.is_super_admin(user_id=ids["super"]) is True
    assert await authority.is_b66_customer_admin(ids["super"]) is False

    class BrokenStore:
        async def role_for(self, user_id):
            raise RuntimeError("migration 052 not applied")

    degraded = PlatformAdminAuthority(
        role_store=BrokenStore(),
        legacy_model_admin=CentralAdmin(ids["super"]),
        legacy_b66_admin=B66Admin(ids["member"]),
    )
    assert await degraded.role_for(ids["super"]) == "SUPER_ADMIN"
    assert await degraded.role_for(ids["admin"]) is None
    assert await degraded.is_global_model_admin(user_id=ids["admin"]) is False


def test_legacy_b66_owner_keeps_customer_admin_without_model_management():
    _, ids = seed_db()
    app, settings, _ = build_app(ids, b66_admin_id=ids["member"])
    member_token = create_session_token(settings, ids["member"])

    session = call(app, settings, "GET", "/api/admin/session", token=member_token)
    assert session.status_code == 200
    assert session.json()["role"] is None
    assert session.json()["capabilities"] == {
        "admin_hub": False,
        "role_management": False,
        "chat_admin": False,
        "claw_admin": False,
        "b66_platform_admin": True,
        "b66_customer_admin": True,
        "central_model_admin": False,
    }
    assert call(
        app, settings, "GET", "/api/b66/admin/model-policy", token=member_token
    ).status_code == 200
    assert call(
        app, settings, "GET", "/api/admin/models/me", token=member_token
    ).status_code == 403


class CentralAdmin:
    def __init__(self, user_id):
        self.user_id = user_id

    async def is_global_model_admin(self, *, user_id):
        return user_id == self.user_id


class B66Admin:
    def __init__(self, user_id):
        self.user_id = user_id

    async def is_google_admin(self, user_id):
        return user_id == self.user_id

    async def model_policy(self):
        return {
            "revision": 0,
            "active": False,
            "tiers": {"FREE": [], "PLUS": [], "PRO": [], "MAX": []},
            "disabled_models": [],
        }

    async def set_model_policy(self, **kwargs):
        return await self.model_policy()


class Resolver:
    async def list_selectable_models(self):
        return [
            {
                "model_id": "google/gemini-3.5-flash-lite",
                "name": "Gemini 3.5 Flash Lite",
            }
        ]

    async def list_registered_models(self):
        return [
            {
                "model_id": "google/gemini-3.5-flash-lite",
                "name": "Gemini 3.5 Flash Lite",
                "provider_id": "google",
                "b14_enabled": True,
                "owner_excluded": False,
                "capabilities": [],
            }
        ]


def build_app(ids, *, b66_admin_id=None):
    settings = Settings.from_values(
        runtime_mode="mock",
        auth_mode="password",
        public_base_url=BASE,
        session_secret="5118-platform-admin-test-session-secret",
        session_max_age_seconds=3600,
    )
    db, _ = seed_db()
    app = create_app(
        settings=settings,
        history_store=SimpleNamespace(),
        central_model_admin_authorizer=CentralAdmin(ids["super"]),
        b66_member_admin_store=B66Admin(b66_admin_id or ids["super"]),
        platform_admin_role_store=D1PlatformAdminRoleStore(db),
    )
    app.state.b66_quote_model_resolver = Resolver()
    app.state.b14_model_choice_resolver = Resolver()
    app.state.b66_inquiry_store = SimpleNamespace()
    return app, settings, db


def call(app, settings, method, path, *, token=None, body=None):
    async def inner():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=BASE
        ) as client:
            if token:
                client.cookies.set(SESSION_COOKIE, token)
            return await client.request(method, path, json=body)

    return asyncio.run(inner())


def test_existing_admin_keeps_central_authority_and_admin_role_does_not_escalate():
    _, ids = seed_db()
    app, settings, db = build_app(ids)
    super_token = create_session_token(settings, ids["super"])
    admin_token = create_session_token(settings, ids["admin"])

    member = call(app, settings, "GET", "/api/admin/session", token=admin_token)
    assert member.status_code == 200
    assert member.json()["role"] is None
    assert member.json()["capabilities"]["admin_hub"] is False

    # The existing trusted operator keeps SUPER_ADMIN before any role row.
    existing = call(app, settings, "GET", "/api/admin/session", token=super_token)
    assert existing.status_code == 200
    assert existing.json()["role"] == "SUPER_ADMIN"
    assert existing.json()["capabilities"] == {
        "admin_hub": True,
        "role_management": True,
        "chat_admin": True,
        "claw_admin": True,
        "b66_platform_admin": True,
        "b66_customer_admin": True,
        "central_model_admin": True,
    }

    assigned = call(
        app, settings, "POST", "/api/admin/roles", token=super_token,
        body={"user_id": ids["admin"], "role": "ADMIN"},
    )
    assert assigned.status_code == 200
    assert assigned.json()["assignment"]["role"] == "ADMIN"

    # The same product session now carries ADMIN; no new login is required.
    admin = call(app, settings, "GET", "/api/admin/session", token=admin_token)
    assert admin.status_code == 200
    assert admin.json()["role"] == "ADMIN"
    assert admin.json()["capabilities"] == {
        "admin_hub": True,
        "role_management": False,
        "chat_admin": True,
        "claw_admin": True,
        "b66_platform_admin": True,
        "b66_customer_admin": False,
        "central_model_admin": True,
    }

    # ADMIN reaches the existing B14/Chat/Claw model-management gate.
    models = call(app, settings, "GET", "/api/admin/models/me", token=admin_token)
    assert models.status_code == 200
    assert models.json()["admin"] is True
    assert models.json()["authority"] == "platform_admin"
    super_models = call(
        app, settings, "GET", "/api/admin/models/me", token=super_token
    )
    assert super_models.status_code == 200
    assert super_models.json()["admin"] is True

    snapshot = call(
        app, settings, "GET", "/api/admin/models/snapshot", token=admin_token
    )
    assert snapshot.status_code == 200
    assert snapshot.json()["b14"]["models"][0]["model_id"] == (
        "google/gemini-3.5-flash-lite"
    )
    preview = call(
        app, settings, "POST", "/api/admin/models/preview", token=admin_token,
        body={
            "model_id": "google/gemini-3.5-flash-lite",
            "targets": [{"product_id": "chat", "tier": "PLUS", "action": "allow"}],
        },
    )
    assert preview.status_code == 200
    assert preview.json()["mode"] == "preview_only"

    # ADMIN reaches B66 platform policy (read and write), never customer data.
    policy = call(
        app, settings, "GET", "/api/b66/admin/model-policy", token=admin_token
    )
    assert policy.status_code == 200
    assert policy.json()["models"][0]["model_id"] == "google/gemini-3.5-flash-lite"
    updated_policy = call(
        app, settings, "PUT", "/api/b66/admin/model-policy", token=admin_token,
        body={
            "expected_revision": 0,
            "active": False,
            "tiers": {
                "FREE": ["google/gemini-3.5-flash-lite"],
                "PLUS": [], "PRO": [], "MAX": [],
            },
            "disabled_models": [],
        },
    )
    assert updated_policy.status_code == 200
    for customer_path in ("/api/b66/admin/members", "/api/b66/admin/inquiries"):
        denied_customer = call(app, settings, "GET", customer_path, token=admin_token)
        assert denied_customer.status_code == 403
    b66 = call(app, settings, "GET", "/api/b66/admin/me", token=admin_token)
    assert b66.status_code == 200
    assert b66.json()["admin"] is False

    # ADMIN cannot grant itself or anyone else.
    denied = call(
        app, settings, "POST", "/api/admin/roles", token=admin_token,
        body={"user_id": ids["member"], "role": "ADMIN"},
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "role_management_forbidden"

    # Revocation is read on the next request from the same session cookie.
    revoked = call(
        app, settings, "DELETE", f"/api/admin/roles/{ids['admin']}",
        token=super_token,
    )
    assert revoked.status_code == 200
    assert revoked.json()["revocation"]["revoked"] is True
    after = call(app, settings, "GET", "/api/admin/session", token=admin_token)
    assert after.status_code == 200
    assert after.json()["role"] is None
    assert call(
        app, settings, "GET", "/api/admin/models/me", token=admin_token
    ).status_code == 403
    assert call(
        app, settings, "GET", "/api/b66/admin/model-policy", token=admin_token
    ).status_code == 403

    audit = db.conn.execute(
        "SELECT previous_role, current_role FROM platform_admin_role_audit "
        "WHERE target_user_id=? ORDER BY id",
        (ids["admin"],),
    ).fetchall()
    assert [(row[0], row[1]) for row in audit] == [
        (None, "ADMIN"),
        ("ADMIN", None),
    ]


def test_role_management_rejects_unknown_accounts_and_unauthenticated_callers():
    _, ids = seed_db()
    app, settings, _ = build_app(ids)
    super_token = create_session_token(settings, ids["super"])
    forged = "usr_" + "e" * 32

    assert call(
        app, settings, "POST", "/api/admin/roles",
        body={"user_id": ids["member"], "role": "ADMIN"},
    ).status_code == 401

    missing = call(
        app, settings, "POST", "/api/admin/roles", token=super_token,
        body={"user_id": forged, "role": "ADMIN"},
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "canonical_user_not_found"

    canonical_but_forged = call(
        app, settings, "POST", "/api/admin/roles", token=super_token,
        body={"user_id": ids["forged"], "role": "ADMIN"},
    )
    assert canonical_but_forged.status_code == 404

    invalid_role = call(
        app, settings, "POST", "/api/admin/roles", token=super_token,
        body={"user_id": ids["member"], "role": "OWNER"},
    )
    assert invalid_role.status_code == 400
    assert invalid_role.json()["error"]["code"] == "invalid_role"

    extra_field = call(
        app, settings, "POST", "/api/admin/roles", token=super_token,
        body={"user_id": ids["member"], "role": "ADMIN", "email": "x@y.test"},
    )
    assert extra_field.status_code == 400

    # Logout clears the product session cookie; the admin surface is unauthenticated.
    logout = call(app, settings, "POST", "/api/auth/logout", token=super_token)
    assert logout.status_code == 200
    set_cookie = logout.headers.get("set-cookie", "").lower()
    assert f"{SESSION_COOKIE}=" in set_cookie
    assert "max-age=0" in set_cookie
    assert call(
        app, settings, "GET", "/api/admin/session"
    ).json()["authenticated"] is False
