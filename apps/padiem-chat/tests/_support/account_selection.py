"""SQLite D1 and signed-account session fixtures for account selection."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import httpx

from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.history import _user_id
from app.main import create_app

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations" / "059_account_model_selection.sql"
BASE = "https://chat.padiem.test"


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
        return [await statement.run() for statement in statements]


def seed_db():
    """One administrator account, one PLUS member and one FREE member."""
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
    admin = _user_id("google-subject-admin")
    plus = _user_id("google-subject-plus")
    free = _user_id("google-subject-free")
    for uid, subject, email in (
        (admin, "google-subject-admin", "admin@example.test"),
        (plus, "google-subject-plus", "plus@example.test"),
        (free, "google-subject-free", "free@example.test"),
    ):
        db.conn.execute(
            "INSERT INTO users VALUES (?,?,?,?,?,?,?,?)",
            (uid, "google", subject, email, "Member", "", "2026-10-01T00:00:00Z", "2026-10-01T00:00:00Z"),
        )
    db.conn.executescript(
        (ROOT / "migrations" / "037_b66_admin_memberships.sql").read_text(encoding="utf-8")
    )
    db.conn.execute(
        "UPDATE b66_memberships SET status='approved', tier='PLUS' WHERE user_id=?", (plus,)
    )
    db.conn.execute(
        "UPDATE b66_memberships SET status='approved', tier='FREE' WHERE user_id=?", (free,)
    )
    db.conn.executescript(MIGRATION.read_text(encoding="utf-8"))
    return db, admin, plus, free


def settings() -> Settings:
    return Settings(
        auth_mode="hybrid",
        session_secret="s" * 48,
        public_base_url=BASE,
        runtime_mode="b14",
    )


def build_app(db):
    return create_app(
        settings(),
        d1_binding=db,
        b66_admin_google_email="admin@example.test",
    )


def session(app, uid) -> dict[str, str]:
    return {SESSION_COOKIE: create_session_token(app.state.settings, uid, canonical_session_id="session_test_a")}


def client_for(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE)
