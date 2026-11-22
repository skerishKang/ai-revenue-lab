"""#8061 26차: shared setup for the password reset tests."""
from __future__ import annotations

import asyncio
import re
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.history import D1HistoryStore, _password_user_id, _user_id
from app.main import create_app
from app.password_auth import hash_password, verify_password
from app.password_reset_store import D1PasswordResetStore

BASE = "https://chat.example.test"

ROOT = Path(__file__).resolve().parents[2]

RESET_MIGRATION = ROOT / "migrations" / "062_password_reset.sql"

ROLE_MIGRATION = ROOT / "migrations" / "052_platform_admin_roles.sql"

SESSION_SECRET = "5441-password-reset-test-session-secret-not-real-000000"

CURRENT_PASSWORD = "correct horse battery staple"

NEW_PASSWORD = "brand new secret phrase"

MEMBER_EMAIL = "member@example.test"

OTHER_EMAIL = "other@example.test"

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

class RecordingDelivery:
    """A network-free mail transport that records what it was asked to send."""

    def __init__(self, *, result: bool = True):
        self.sent: list[dict] = []
        self.result = result

    async def send(self, *, to, subject, text):
        self.sent.append({"to": to, "subject": subject, "text": text})
        return self.result

class CanonicalAuthority:
    """The minimal canonical authority the reset route uses."""

    def __init__(self, *, fail: bool = False):
        self.revoked_all: list[tuple[str, str]] = []
        self.revoked_one: list[tuple[str, str]] = []
        self.fail = fail

    async def revoke_auth_session(self, *, product_id, session_id):
        self.revoked_one.append((product_id, session_id))

    async def revoke_all_auth_sessions(self, *, product_id, product_user_id):
        if self.fail:
            raise RuntimeError("canonical authority is unavailable")
        self.revoked_all.append((product_id, product_user_id))

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
    member_uid = _password_user_id(MEMBER_EMAIL)
    other_uid = _password_user_id(OTHER_EMAIL)
    for uid, subject, email in (
        (owner_uid, "google-owner", "owner@example.test"),
        (member_uid, "password:" + MEMBER_EMAIL, MEMBER_EMAIL),
        (other_uid, "password:" + OTHER_EMAIL, OTHER_EMAIL),
    ):
        db.conn.execute(
            "INSERT INTO users VALUES (?,?,?,?,?,?,?,?)",
            (uid, "google", subject, email, "Member Test", "", now, now),
        )
    db.conn.execute(
        "INSERT INTO password_credentials(user_id, username, password_hash, "
        "failed_attempts, locked_until, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
        (member_uid, MEMBER_EMAIL, hash_password(CURRENT_PASSWORD), 0, None, now, now),
    )
    db.conn.execute(
        "INSERT INTO password_credentials(user_id, username, password_hash, "
        "failed_attempts, locked_until, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
        (other_uid, OTHER_EMAIL, hash_password("other account secret"), 0, None, now, now),
    )
    db.conn.executescript(ROLE_MIGRATION.read_text(encoding="utf-8"))
    db.conn.executescript(RESET_MIGRATION.read_text(encoding="utf-8"))
    db.conn.execute(
        "INSERT INTO platform_admin_roles(user_id, role, granted_by, created_at, updated_at) "
        "VALUES (?,?,?,?,?)",
        (member_uid, "ADMIN", owner_uid, now, now),
    )
    return db, {
        "google": owner_uid,
        "member": member_uid,
        "other": other_uid,
        "member_email": MEMBER_EMAIL,
        "other_email": OTHER_EMAIL,
    }

def password_settings():
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="password",
        public_base_url=BASE,
        session_secret=SESSION_SECRET,
        session_max_age_seconds=3600,
    )

def build_app(db, *, delivery=None, authority=None):
    settings = password_settings()
    app = create_app(
        settings=settings,
        history_store=D1HistoryStore(db),
        password_reset_store=D1PasswordResetStore(db),
        password_reset_delivery=delivery,
        control_plane_identity_authority=authority,
    )
    return app, settings

def call(app, method, path, *, token=None, body=None):
    async def inner():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=BASE
        ) as client:
            if token:
                client.cookies.set(SESSION_COOKIE, token)
            return await client.request(method, path, json=body)

    return asyncio.run(inner())

def request_reset(app, email):
    return call(app, "POST", "/api/auth/password/reset/request", body={"email": email})

def confirm_reset(app, token, new_password=NEW_PASSWORD):
    return call(
        app,
        "POST",
        "/api/auth/password/reset/confirm",
        body={"token": token, "new_password": new_password},
    )

def _token_from_mail(delivery) -> str:
    assert delivery.sent, "no reset mail was sent"
    text = delivery.sent[0]["text"]
    match = re.search(r"#reset=([A-Za-z0-9_\-]+)", text)
    assert match, "the reset mail carries no one-time link"
    return match.group(1)

def _stored_hash(db, user_id) -> str:
    row = db.conn.execute(
        "SELECT password_hash FROM password_credentials WHERE user_id=?", (user_id,)
    ).fetchone()
    return str(row["password_hash"])
