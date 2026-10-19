"""D1 owner and cryptographic AAD contract for GitHub credentials."""
from __future__ import annotations
import asyncio
import hashlib
import sqlite3
import time
import pytest

from app.github_oauth_store import D1GitHubOAuthStore

class Statement:
    def __init__(self, conn, query):
        self.conn = conn
        self.query = query
        self.parameters = ()
    def bind(self, *values):
        self.parameters = values
        return self
    async def run(self):
        self.conn.execute(self.query, self.parameters)
        self.conn.commit()
    async def first(self):
        cursor = self.conn.execute(self.query, self.parameters)
        row = cursor.fetchone()
        self.conn.commit()
        return dict(row) if row else None

class SQLiteD1:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
            CREATE TABLE users(id TEXT PRIMARY KEY);
            INSERT INTO users(id) VALUES('user-a'),('user-b');
        """)
        from pathlib import Path
        sql = Path(__file__).resolve().parents[1] / "migrations" / "046_claw_github_app_oauth.sql"
        self.conn.executescript(sql.read_text(encoding="utf-8"))
    def prepare(self, query):
        return Statement(self.conn, query)

class FakeAuthenticatedCipher:
    def random_bytes(self, size):
        assert size == 12
        return b"x" * 12
    async def encrypt(self, *, key, iv, plaintext, additional_data):
        tag = hashlib.sha256(key + iv + additional_data).digest()
        return tag + bytes(x ^ tag[i%len(tag)] for i,x in enumerate(plaintext))
    async def decrypt(self, *, key, iv, ciphertext, additional_data):
        tag = hashlib.sha256(key + iv + additional_data).digest()
        if ciphertext[:32] != tag:
            raise ValueError("AAD mismatch")
        return bytes(x ^ tag[i%len(tag)] for i,x in enumerate(ciphertext[32:]))

@pytest.mark.asyncio
async def test_one_use_state_requires_same_session_and_owner():
    store = D1GitHubOAuthStore(SQLiteD1(), session_secret="s" * 64, cipher=FakeAuthenticatedCipher())
    await store.begin(user_id="user-a",session="session-a",state="nonce-a",verifier="pkce-a",now=100)
    assert await store.consume(user_id="user-b",session="session-a",state="nonce-a",now=110) is None
    assert await store.consume(user_id="user-a",session="session-b",state="nonce-a",now=110) is None
    assert await store.consume(user_id="user-a",session="session-a",state="nonce-a",now=110)=="pkce-a"
    assert await store.consume(user_id="user-a",session="session-a",state="nonce-a",now=111) is None
    await store.begin(user_id="user-a",session="session-a",state="nonce-b",verifier="pkce-b",now=100)
    assert await store.consume(user_id="user-a",session="session-a",state="nonce-b",now=701) is None

@pytest.mark.asyncio
async def test_tokens_sealed_owner_scoped_and_off_persists():
    d1=SQLiteD1()
    store = D1GitHubOAuthStore(d1,session_secret="s" * 64,cipher=FakeAuthenticatedCipher())
    deadline = int(time.time()) + 100000
    common=dict(github_user_id=12,login="owner",installation_id=171513671,
                access_token="ghu_owner123",refresh_token="ghr_owner123",
                access_expires_at=int(time.time())+3600,refresh_expires_at=deadline)
    await store.save(user_id="user-a",**common)
    assert b"ghu_owner123" not in str(list(d1.conn.execute("SELECT sealed_credential FROM claw_github_connections"))).encode()
    assert (await store.token_pair("user-a"))["access_token"] == "ghu_owner123"
    assert (await store.status("user-a"))["enabled"] is True
    await store.set_enabled("user-a", False)
    assert (await store.status("user-a"))["enabled"] is False
    assert (await store.token_pair("user-a"))["access_token"] == "ghu_owner123"
    await store.set_enabled("user-a", True)
    assert (await store.status("user-a"))["enabled"] is True
    assert await store.token_pair("user-b") is None
    await store.save(user_id="user-b",**{**common,"access_token":"ghu_other","refresh_token":"ghr_other"})
    await store.disconnect("user-a")
    assert await store.status("user-a") is None
    assert (await store.token_pair("user-b"))["access_token"] == "ghu_other"
    await store.disconnect("user-a")
