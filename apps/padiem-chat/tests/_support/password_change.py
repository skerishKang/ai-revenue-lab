"""공용 시험 준비 — 비밀번호 변경 앱·DB 더미.

test_5434_password_change가 들고 있던 씨드·앱·호출 준비를 여기 옮겨
시험끼리 import가 없게 한다(#8061).
"""
from __future__ import annotations

import asyncio
import sqlite3
from types import SimpleNamespace

import httpx

from app.auth import SESSION_COOKIE
from app.config import Settings
from app.history import D1HistoryStore, _password_user_id, _user_id
from app.main import create_app
from app.password_auth import hash_password
from _support import password_change_static as change_assets

BASE = "https://chat.example.test"
SESSION_SECRET = "5434-password-change-test-session-secret-not-real-00000"
CURRENT_PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "brand new secret phrase"


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


class CanonicalAuthority:
    """The minimal canonical authority the change route and the logout share."""

    def __init__(self):
        self.revoked: list[tuple[str, str]] = []

    async def revoke_auth_session(self, *, product_id, session_id):
        self.revoked.append((product_id, session_id))


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
    now = "2026-10-01T00:00:00Z"
    owner_uid = _user_id("google-owner")
    owner_email = "owner@example.test"
    member_uid = _password_user_id(owner_email)
    other_uid = _password_user_id("other@example.test")
    for uid, subject, email in (
        (owner_uid, "google-owner", owner_email),
        (member_uid, "password:" + owner_email, owner_email),
        (other_uid, "password:other@example.test", "other@example.test"),
    ):
        db.conn.execute(
            "INSERT INTO users VALUES (?,?,?,?,?,?,?,?)",
            (uid, "google", subject, email, "Owner Test", "", now, now),
        )
    db.conn.execute(
        "INSERT INTO password_credentials(user_id, username, password_hash, "
        "failed_attempts, locked_until, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
        (member_uid, owner_email, hash_password(CURRENT_PASSWORD), 0, None, now, now),
    )
    db.conn.execute(
        "INSERT INTO password_credentials(user_id, username, password_hash, "
        "failed_attempts, locked_until, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
        (other_uid, "other@example.test", hash_password("other account secret"), 0, None, now, now),
    )
    db.conn.executescript(change_assets.role_migration_source())
    db.conn.execute(
        "INSERT INTO platform_admin_roles(user_id, role, granted_by, created_at, updated_at) "
        "VALUES (?,?,?,?,?)",
        (member_uid, "ADMIN", owner_uid, now, now),
    )
    return db, {
        "google": owner_uid,
        "member": member_uid,
        "other": other_uid,
        "member_email": owner_email,
    }


def password_settings():
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="password",
        public_base_url=BASE,
        session_secret=SESSION_SECRET,
        session_max_age_seconds=3600,
    )


def build_app(db):
    settings = password_settings()
    authority = CanonicalAuthority()
    app = create_app(
        settings=settings,
        history_store=D1HistoryStore(db),
        control_plane_identity_authority=authority,
    )
    return app, settings, authority


def call(app, settings, method, path, *, token=None, body=None):
    async def inner():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=BASE
        ) as client:
            if token:
                client.cookies.set(SESSION_COOKIE, token)
            return await client.request(method, path, json=body)

    return asyncio.run(inner())
