"""#5483 administrator and member model entitlement alignment.

The administrator hub and the model tier ceiling were judged by two different
server authorities. An account that the server already proves to be a platform
administrator (#5118 stored role) saw the administrator menu while the model
picker still reported the ordinary member grade, so every paid tier was
presented as an upgrade and the account could not reach the highest model it
was entitled to.

These regressions prove the **server judgment path**, not the browser copy:

* the administrator model ceiling follows the same authority as the
  administrator hub;
* an ordinary member keeps exactly its own grade;
* a higher grade may use a lower tier, never a higher one;
* the model-request gate (Chat/Claw) and the final dispatch guard agree with
  the ceiling;
* a revoked or unreadable administrator authority never keeps a paid tier.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.history import _user_id
from app.main import create_app
from app.model_policy import request_tier_context, resolve_tier_policy
from app.platform_admin_roles import D1PlatformAdminRoleStore

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://chat.padiem.test"
MIGRATION_MEMBERSHIP = ROOT / "migrations" / "037_b66_admin_memberships.sql"
MIGRATION_ROLES = ROOT / "migrations" / "052_platform_admin_roles.sql"
MIGRATION_SELECTION = ROOT / "migrations" / "059_account_model_selection.sql"

OPERATOR_EMAIL = "operator@example.test"
ADMIN_EMAIL = "admin@example.test"
PLUS_EMAIL = "plus@example.test"
FREE_EMAIL = "free@example.test"

AUTH_STATUS = "/api/auth/status"
MODEL_SELECTION = "/api/account/model-selection"


# ── a SQLite-backed stand-in for the canonical PADIEM_CHAT_DB D1 ────────────


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
    """The Production shape: one operator, one stored ADMIN, two members."""
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
    ids = {
        "operator": _user_id("google-operator"),
        "admin": _user_id("google-admin"),
        "plus": _user_id("google-plus"),
        "free": _user_id("google-free"),
    }
    for key, email in (
        ("operator", OPERATOR_EMAIL),
        ("admin", ADMIN_EMAIL),
        ("plus", PLUS_EMAIL),
        ("free", FREE_EMAIL),
    ):
        db.conn.execute(
            "INSERT INTO users VALUES (?,?,?,?,?,?,?,?)",
            (
                ids[key], "google", f"google-{key}", email, "Account", "",
                "2026-10-01T00:00:00Z", "2026-10-01T00:00:00Z",
            ),
        )
    db.conn.executescript(MIGRATION_MEMBERSHIP.read_text(encoding="utf-8"))
    # The stored administrator is a pending FREE member: the exact Production
    # state that showed the administrator menu next to a Free-only picker.
    db.conn.execute(
        "UPDATE b66_memberships SET status='pending', tier='FREE' WHERE user_id=?",
        (ids["admin"],),
    )
    db.conn.execute(
        "UPDATE b66_memberships SET status='approved', tier='PLUS' WHERE user_id=?",
        (ids["plus"],),
    )
    db.conn.execute(
        "UPDATE b66_memberships SET status='approved', tier='FREE' WHERE user_id=?",
        (ids["free"],),
    )
    db.conn.executescript(MIGRATION_ROLES.read_text(encoding="utf-8"))
    db.conn.executescript(MIGRATION_SELECTION.read_text(encoding="utf-8"))
    return db, ids


def settings() -> Settings:
    return Settings.from_values(
        runtime_mode="b14",
        b14_base_url="https://b14.internal",
        auth_mode="password",
        public_base_url=BASE,
        session_secret="5483-entitlement-alignment-session-secret",
    )


class _HistoryStore:
    """The minimal account projection the auth status route needs."""

    async def get_user(self, user_id):
        from app.history import UserProfile

        return UserProfile(
            id=user_id,
            email="member@example.test",
            display_name="Account",
            picture_url="",
        )

    async def find_password_credential_by_user_id(self, user_id):
        return None


def build_app(db):
    return create_app(
        settings=settings(),
        history_store=_HistoryStore(),
        d1_binding=db,
        b66_admin_google_email=OPERATOR_EMAIL,
        central_model_admin_google_email=OPERATOR_EMAIL,
        platform_admin_role_store=D1PlatformAdminRoleStore(db),
    )


async def grant_admin_role(db, ids):
    """Grant the stored platform role through the reviewed role store."""
    store = D1PlatformAdminRoleStore(db)
    await store.assign(
        actor_user_id=ids["operator"], target_user_id=ids["admin"], role="ADMIN"
    )


def cookies(app, uid):
    return {SESSION_COOKIE: create_session_token(app.state.settings, uid)}


def client_for(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE)


def _error_code(response) -> str | None:
    try:
        payload = response.json()
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if isinstance(error, dict):
        code = error.get("code")
        if isinstance(code, str):
            return code
    return None


# ── the administrator ceiling follows the administrator hub ──────────────────


@pytest.mark.asyncio
async def test_the_administrator_ceiling_follows_the_administrator_hub():
    db, ids = seed_db()
    await grant_admin_role(db, ids)
    app = build_app(db)
    async with client_for(app) as client:
        # The hub already proves the platform role to this account.
        session = await client.get("/api/admin/session", cookies=cookies(app, ids["admin"]))
        assert session.status_code == 200
        assert session.json()["role"] == "ADMIN"
        assert session.json()["capabilities"]["admin_hub"] is True

        # The model ceiling is now the same authority, not the member record.
        status = await client.get(AUTH_STATUS, cookies=cookies(app, ids["admin"]))
        assert status.status_code == 200
        assert status.json()["member_grade"] == "max"

        selection = await client.get(MODEL_SELECTION, cookies=cookies(app, ids["admin"]))
        assert selection.status_code == 200
        body = selection.json()
        assert body["allowed_tiers"] == ["free", "plus", "pro", "max"]
        # The administrator-only model lane keeps its own operator-scoped
        # contract; this fix does not widen it.
        assert body["admin_available"] is False


@pytest.mark.asyncio
async def test_an_ordinary_member_keeps_exactly_its_own_grade():
    db, ids = seed_db()
    app = build_app(db)
    async with client_for(app) as client:
        plus = await client.get(AUTH_STATUS, cookies=cookies(app, ids["plus"]))
        assert plus.json()["member_grade"] == "plus"
        plus_selection = await client.get(
            MODEL_SELECTION, cookies=cookies(app, ids["plus"])
        )
        assert plus_selection.json()["allowed_tiers"] == ["free", "plus"]

        free = await client.get(AUTH_STATUS, cookies=cookies(app, ids["free"]))
        assert free.json()["member_grade"] == "free"
        free_selection = await client.get(
            MODEL_SELECTION, cookies=cookies(app, ids["free"])
        )
        assert free_selection.json()["allowed_tiers"] == ["free"]

        # An account without an approved membership record is never a paid
        # member, administrator or not.
        pending = await client.get(AUTH_STATUS, cookies=cookies(app, ids["admin"]))
        assert pending.json()["member_grade"] == "free"


@pytest.mark.asyncio
async def test_the_model_request_gate_serves_the_administrator_the_top_tier():
    db, ids = seed_db()
    await grant_admin_role(db, ids)
    app = build_app(db)
    payload = {"messages": [{"role": "user", "content": "안녕하세요"}], "tier": "max"}
    async with client_for(app) as client:
        administrator = await client.post(
            "/api/chat", json=payload, cookies=cookies(app, ids["admin"])
        )
        # The administrator passes the model-request grade gate. Whatever the
        # downstream provider result is, the tier gate is not the blocker.
        assert _error_code(administrator) != "tier_not_available"

        member = await client.post(
            "/api/chat", json=payload, cookies=cookies(app, ids["plus"])
        )
        assert member.status_code == 403
        assert _error_code(member) == "tier_not_available"

        free_member = await client.post(
            "/api/chat", json=payload, cookies=cookies(app, ids["free"])
        )
        assert free_member.status_code == 403
        assert _error_code(free_member) == "tier_not_available"


@pytest.mark.asyncio
async def test_a_higher_grade_may_use_a_lower_tier_but_never_a_higher_one():
    db, ids = seed_db()
    await grant_admin_role(db, ids)
    app = build_app(db)
    async with client_for(app) as client:
        for tier in ("free", "plus", "pro", "max"):
            allowed = await client.put(
                MODEL_SELECTION,
                headers={"Origin": BASE, "Content-Type": "application/json"},
                cookies=cookies(app, ids["admin"]),
                json={"tier": tier},
            )
            assert allowed.status_code == 200, tier
            assert allowed.json()["selection"]["tier"] == tier

        # A PLUS member reaches its own tier and everything below it only.
        for tier in ("free", "plus"):
            allowed = await client.put(
                MODEL_SELECTION,
                headers={"Origin": BASE, "Content-Type": "application/json"},
                cookies=cookies(app, ids["plus"]),
                json={"tier": tier},
            )
            assert allowed.status_code == 200, tier
        for tier in ("pro", "max"):
            denied = await client.put(
                MODEL_SELECTION,
                headers={"Origin": BASE, "Content-Type": "application/json"},
                cookies=cookies(app, ids["plus"]),
                json={"tier": tier},
            )
            assert denied.status_code == 403, tier
            assert _error_code(denied) == "tier_not_available"


@pytest.mark.asyncio
async def test_a_revoked_administrator_role_restores_the_member_grade():
    db, ids = seed_db()
    await grant_admin_role(db, ids)
    app = build_app(db)
    async with client_for(app) as client:
        assert (
            await client.get(AUTH_STATUS, cookies=cookies(app, ids["admin"]))
        ).json()["member_grade"] == "max"

        await D1PlatformAdminRoleStore(db).revoke(
            actor_user_id=ids["operator"], target_user_id=ids["admin"]
        )

        after = await client.get(AUTH_STATUS, cookies=cookies(app, ids["admin"]))
        assert after.json()["member_grade"] == "free"
        selection = await client.get(
            MODEL_SELECTION, cookies=cookies(app, ids["admin"])
        )
        assert selection.json()["allowed_tiers"] == ["free"]
        refused = await client.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": "안녕하세요"}], "tier": "max"},
            cookies=cookies(app, ids["admin"]),
        )
        assert refused.status_code == 403
        assert _error_code(refused) == "tier_not_available"


@pytest.mark.asyncio
async def test_an_unreadable_administrator_authority_never_elevates():
    db, ids = seed_db()
    await grant_admin_role(db, ids)
    app = build_app(db)

    class _BrokenRoleStore:
        async def role_for(self, user_id):
            raise RuntimeError("role table unavailable")

    from app.central_model_admin_identity import D1CentralModelAdminAuthorizer
    from app.platform_admin_authority import PlatformAdminAuthority

    # The stored role can no longer be read. The trusted operator binding
    # still answers for the operator account; the stored administrator does
    # not, so the account falls back to its own membership grade.
    app.state.platform_admin_authority = PlatformAdminAuthority(
        role_store=_BrokenRoleStore(),
        legacy_model_admin=D1CentralModelAdminAuthorizer(
            db, verified_owner_email=OPERATOR_EMAIL
        ),
        legacy_b66_admin=app.state.b66_member_admin_store,
    )
    async with client_for(app) as client:
        status = await client.get(AUTH_STATUS, cookies=cookies(app, ids["admin"]))
        assert status.json()["member_grade"] == "free"
        refused = await client.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": "안녕하세요"}], "tier": "max"},
            cookies=cookies(app, ids["admin"]),
        )
        assert refused.status_code == 403
        assert _error_code(refused) == "tier_not_available"


# ── the dispatch boundary agrees with the ceiling ───────────────────────────


@pytest.mark.asyncio
async def test_the_dispatched_model_follows_the_verified_ceiling():
    """The tier the route resolves must be the tier the server verified."""
    from app.member_grade_access import verified_member_grade

    db, ids = seed_db()
    await grant_admin_role(db, ids)
    app = build_app(db)
    request = SimpleNamespace(app=SimpleNamespace(state=app.state))

    grade = await verified_member_grade(request, ids["admin"])
    assert grade == "max"

    with request_tier_context(grade):
        policy = resolve_tier_policy(
            [{"role": "user", "content": "안녕하세요"}], grade
        )
    assert policy.model_id
    # The ceiling is the product tier label the guard compares at dispatch.
    assert policy.profile == "high"
