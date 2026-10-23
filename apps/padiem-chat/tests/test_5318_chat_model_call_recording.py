"""#5318 slice A: Chat records a model call after a successful completion."""
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.main import create_app
from app.model_call_record_store import D1ModelCallRecordStore, ModelCallRecordInput

from test_public_streaming import ScriptedClient, _event

OWNER = "usr_" + "a" * 32
ORIGIN = "https://chat.example.test"
SECRET = "5318-record-test-secret-not-real-000000000000"
BASE = "chat.example.test"


class EmptyHistory:
    async def get_conversation(self, user_id, conversation_id, *, product_scope):
        return None

    async def get_conversation_model_context(self, user_id, conversation_id, *, product_scope):
        return None

    async def append_exchange(self, user_id, conversation_id, user_text, assistant_text, project_id=None, *, product_scope):
        return conversation_id or ("chat_" + "1" * 32)


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
        return _Result([])

    async def all(self):
        cur = self.conn.execute(self.query, self.parameters)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        self.conn.commit()
        return _Result(rows)


class _Result:
    def __init__(self, rows):
        self.results = rows


class SQLiteD1:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        migrations = Path(__file__).resolve().parents[1] / "migrations"
        for name in ("067_model_call_records.sql",):
            self.conn.executescript((migrations / name).read_text(encoding="utf-8"))

    def prepare(self, query):
        return Statement(self.conn, query)


def settings():
    return Settings.from_values(
        runtime_mode="b14",
        b14_base_url="https://b14.internal",
        live_enabled=False,
        auth_mode="google",
        public_base_url=ORIGIN,
        google_client_id="5318-client.apps.googleusercontent.com",
        google_client_secret="5318-test-only-secret",
        session_secret=SECRET,
        session_max_age_seconds=3600,
    )


def test_chat_records_a_model_call_after_completion():
    d1 = SQLiteD1()
    store = D1ModelCallRecordStore(d1)
    app = create_app(settings(), history_store=EmptyHistory())
    app.state.model_call_record_store = store
    class CompleteClient:
        def __init__(self):
            self.calls = 0
        async def stream_text_auto(self, messages, **kwargs):
            self.calls += 1
            yield _event("안녕하세요")
            yield _event(None, done=True)
        async def complete(self, messages, **kwargs):
            self.calls += 1
            return {"answer": "정상 답변", "runtime": "test", "route": {"mode": "manual", "model": "test/model", "provider": "test-provider"}}
    scripted = CompleteClient()
    app.state.b14_client = scripted
    cookie = create_session_token(settings(), OWNER)

    async def run():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as client:
            client.cookies.set(SESSION_COOKIE, cookie, domain=BASE, path="/")
            response = await client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "hi"}], "mode": "auto"},
                headers={"Origin": ORIGIN},
            )
            assert response.status_code == 200, response.text
        # Give the best-effort record a chance to land.
        await asyncio.sleep(0.1)
        recent = await store.list_recent(product="chat", limit=10)
        assert len(recent) == 1, recent
        assert recent[0].status == "success"
        assert recent[0].provider_id != "unknown" or recent[0].model_id != "unknown"

    asyncio.run(run())
