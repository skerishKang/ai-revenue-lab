"""#8061 24차: shared setup for the BYOK product E2E tests."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import httpx
import pytest

from app import chat_routes
from app.auth import SESSION_COOKIE, create_session_token
from app.b14_client import ChatRuntimeError, PADIEM_IDENTITY_INSTRUCTION
from app.byok_client import CustomProviderClient
from app.byok_credentials import D1CustomProviderCredentialStore
from app.config import Settings
from app.history import D1HistoryStore, PRODUCT_SCOPE_CHAT
from app.main import create_app

SESSION_SECRET = "byok-5002-product-e2e-session-secret"

CUSTOM_KEY_SECRET = "byok-5002-product-e2e-custom-key-secret"

CUSTOM_KEY = "sk-customer-owned-5002-key-AAAA1111"

OTHER_KEY = "sk-customer-owned-5002-key-BBBB2222"

ROTATED_KEY = "sk-customer-owned-5002-key-CCCC3333"

OWNER = "usr_" + "a" * 32

OTHER = "usr_" + "b" * 32

PROVIDER_ID = "opencode-go"

MODEL_ID = "opencode-go/beam-free"

ORIGIN = "https://chat.example.test"

PROVIDER_URL = "https://opencode.ai/inference/go/v1/chat/completions"

DEFAULT_ANSWER = "custom 답변"

MIGRATIONS = (
    "001_auth_history.sql",
    "002_projects.sql",
    "042_conversation_product_scope.sql",
    "053_chat_custom_provider_credentials.sql",
    "105_conversation_soft_delete.sql",
    "125_byok_probe_windows.sql",
)

def settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url=ORIGIN,
        google_client_id="5002-client.apps.googleusercontent.com",
        google_client_secret="unit-test-google-secret",
        session_secret=SESSION_SECRET,
        custom_key_secret=CUSTOM_KEY_SECRET,
        session_max_age_seconds=3600,
        byok_via_b14=False,
    )

class Statement:
    """Minimal D1 prepared-statement adapter with the result shapes used here."""

    def __init__(self, conn: sqlite3.Connection, query: str):
        self.conn = conn
        self.query = query
        self.parameters: tuple = ()

    def bind(self, *values):
        self.parameters = values
        return self

    def _execute(self):
        return self.conn.execute(self.query, self.parameters)

    async def run(self):
        cursor = self._execute()
        rows = [dict(row) for row in cursor.fetchall()] if cursor.description else []
        self.conn.commit()
        return {"results": rows}

    async def first(self):
        row = self._execute().fetchone()
        self.conn.commit()
        return dict(row) if row else None

    async def all(self):
        rows = [dict(row) for row in self._execute().fetchall()]
        self.conn.commit()
        return rows

class SQLiteD1:
    """SQLite-backed D1 substitute loaded from the repository migrations."""

    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        migrations = Path(__file__).resolve().parents[2] / "migrations"
        for name in MIGRATIONS:
            self.conn.executescript((migrations / name).read_text(encoding="utf-8"))
        now = "2026-10-19T00:00:00Z"
        for uid, email in ((OWNER, "owner@example.test"), (OTHER, "other@example.test")):
            self.conn.execute(
                "INSERT INTO users "
                "(id, auth_provider, provider_subject, email, display_name, picture_url, created_at, updated_at) "
                "VALUES (?, 'google', ?, ?, ?, '', ?, ?)",
                (uid, "subject-" + uid, email, email.split("@", 1)[0], now, now),
            )
        self.conn.commit()

    def prepare(self, query: str) -> Statement:
        return Statement(self.conn, query)

    def conversations(self) -> list[dict]:
        return [
            dict(row)
            for row in self.conn.execute(
                "SELECT id, user_id, title, product_scope FROM conversations ORDER BY created_at, id"
            )
        ]

    def messages(self, conversation_id: str) -> list[dict]:
        return [
            dict(row)
            for row in self.conn.execute(
                "SELECT role, content, sequence_number FROM messages "
                "WHERE conversation_id=? ORDER BY sequence_number ASC",
                (conversation_id,),
            )
        ]

    def sealed_credentials(self) -> list[str]:
        return [
            row[0]
            for row in self.conn.execute(
                "SELECT sealed_credential FROM chat_custom_provider_credentials"
            )
        ]

class FakeAuthenticatedCipher:
    """Deterministic authenticated cipher; also enforces the owner AAD."""

    def random_bytes(self, size: int) -> bytes:
        assert size == 12
        return b"x" * 12

    async def encrypt(self, *, key, iv, plaintext, additional_data):
        tag = hashlib.sha256(key + iv + additional_data).digest()
        return tag + bytes(value ^ tag[index % len(tag)] for index, value in enumerate(plaintext))

    async def decrypt(self, *, key, iv, ciphertext, additional_data):
        tag = hashlib.sha256(key + iv + additional_data).digest()
        if ciphertext[:32] != tag:
            raise ValueError("AAD mismatch")
        return bytes(value ^ tag[index % len(tag)] for index, value in enumerate(ciphertext[32:]))

class ProviderRecorder:
    def __init__(self, handler=None):
        self.requests: list[httpx.Request] = []
        self._handler = handler or (
            lambda request: httpx.Response(
                200,
                json={
                    "model": "beam-free",
                    "choices": [{"message": {"content": DEFAULT_ANSWER}}],
                },
            )
        )
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._handler(request)

    def sent(self, index: int) -> dict:
        return json.loads(self.requests[index].content)

    def authorization(self, index: int) -> str:
        return self.requests[index].headers["authorization"]

class B14Probe:
    """Failing B14 client; any managed dispatch is counted and refused."""

    def __init__(self):
        self.complete_calls = 0
        self.stream_calls = 0

    async def complete(self, *args, **kwargs):
        self.complete_calls += 1
        raise ChatRuntimeError(502, "b14_injected_failure", "B14 failure injected")

    def stream_text_auto(self, *args, **kwargs):
        self.stream_calls += 1
        raise ChatRuntimeError(502, "b14_injected_failure", "B14 failure injected")

    def with_guard(self, guard):
        raise AssertionError("B14 guard path entered on BYOK_DIRECT")

    @property
    def calls(self) -> int:
        return self.complete_calls + self.stream_calls

def build_app(recorder=None):
    d1 = SQLiteD1()
    history = D1HistoryStore(d1)
    credential_store = D1CustomProviderCredentialStore(
        d1,
        key_secret=CUSTOM_KEY_SECRET,
        session_secret=SESSION_SECRET,
        cipher=FakeAuthenticatedCipher(),
    )
    recorder = recorder or ProviderRecorder()
    app = create_app(
        settings(),
        history_store=history,
        custom_credential_store=credential_store,
        custom_provider_client=CustomProviderClient(transport=recorder.transport),
    )
    app.state.b14_client = B14Probe()
    app.state.b14_catalog_source = None
    app.state.central_model_policy_store = None
    app.state.usage_gate_enforced = False
    return app, d1, history, credential_store, recorder

async def request(app, method, path, *, uid=None, json_body=None, headers=None):
    request_headers = {"Origin": ORIGIN}
    request_headers.update(headers or {})
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=ORIGIN,
    ) as client:
        if uid:
            client.cookies.set(SESSION_COOKIE, create_session_token(settings(), uid, canonical_session_id="session_test_a"))
        return await client.request(
            method, path, json=json_body, headers=request_headers
        )

def sse_events(text: str):
    events = []
    for block in text.strip().split("\n\n"):
        event, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        if event:
            events.append((event, data))
    return events

async def save_key(app, uid, api_key):
    response = await request(
        app, "PUT", "/api/chat/custom/credential", uid=uid,
        json_body={"provider": PROVIDER_ID, "api_key": api_key},
    )
    assert response.status_code == 200, response.text
    return response
