"""공용 시험 준비 — 비밀번호 RPC(서명·호출·잠금) 더미.

test_password_rpc_261106이 들고 있던 빌더·서명·호출 준비를 여기 옮겨
시험끼리 import가 없게 한다(#8061).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import sqlite3
import time
import uuid
from types import SimpleNamespace

import httpx

from app.config import Settings
from app.history import D1HistoryStore
from app.main import create_app
from app.password_auth import hash_password
from app.queue_store_proxy import QueueForwardingHistoryStore

from _support.account_isolation_sweep import apply_all_migrations

BASE = "https://chat.example.test"
SECRET = "chat-test-password-rpc-secret-value-000000"
VERIFY_PATH = "/internal/password-verify"
REGISTER_PATH = "/internal/password-register"
EMAIL = "user@example.test"
PASSWORD = "good-password-123"


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

    def prepare(self, sql):
        return Statement(self, sql)

    async def batch(self, statements):
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            results = []
            for statement in statements:
                cursor = self.conn.execute(statement.sql, statement.params)
                results.append(SimpleNamespace(
                    results=[dict(row) for row in cursor.fetchall()],
                    meta={"changes": cursor.rowcount},
                ))
            self.conn.execute("COMMIT")
            return results
        except Exception:
            self.conn.execute("ROLLBACK")
            raise


class UnexpectedQueueCall:
    async def call(self, *args, **kwargs):
        raise AssertionError("password RPC must keep replay state in the local history store")


def build(secret=SECRET, *, queue_wrapped=False):
    db = SqliteD1()
    apply_all_migrations(db)
    store = D1HistoryStore(db)
    asyncio.run(store.register_password_user(EMAIL, EMAIL, "User", hash_password(PASSWORD)))
    if queue_wrapped:
        store = QueueForwardingHistoryStore(store, client=UnexpectedQueueCall())
    settings = Settings.from_values(
        runtime_mode="mock",
        auth_mode="password",
        public_base_url=BASE,
        session_secret="password-rpc-test-session-secret-000000",
        session_max_age_seconds=3600,
        password_rpc_secret=secret,
    )
    app = create_app(settings=settings, d1_binding=db, history_store=store)
    return app, db


def proof_headers(secret, path, body, *, at=None, service_id=None):
    at = int(time.time()) if at is None else at
    service_id = str(uuid.uuid4()) if service_id is None else service_id
    signed = b"\n".join((b"v2", b"POST", path.encode(), str(at).encode(), service_id.encode(), body))
    proof = "v2=" + hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return {
        "content-type": "application/json",
        "x-padiem-service-at": str(at),
        "x-padiem-service-id": service_id,
        "x-padiem-service-proof": proof,
    }


def rpc(app, path, payload=None, *, secret=SECRET, at=None, service_id=None, raw=None):
    body = raw if raw is not None else json.dumps(payload, separators=(",", ":")).encode()
    headers = proof_headers(secret, path, body, at=at, service_id=service_id)

    async def inner():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=BASE
        ) as client:
            return await client.post(path, content=body, headers=headers)

    return asyncio.run(inner())


def failed_attempts(db, email=EMAIL):
    async def inner():
        store = D1HistoryStore(db)
        credential = await store.find_password_credential(email)
        return credential

    credential = asyncio.run(inner())
    return credential.failed_attempts, credential.locked_until
