"""#5002 PADIEM Custom (BYOK) product E2E over the real Chat history store.

This module exercises the product path end to end inside one ASGI app:

* the signed browser session -> ``/api/chat`` and ``/api/chat/stream``,
* the owner-scoped credential store,
* the real ``D1HistoryStore`` SQL adapter over SQLite with the checked-in
  migrations, and
* ``CustomProviderClient`` over ``httpx.MockTransport``.

The provider transport is a substitute, so a pass here is
``PRODUCT_E2E_BYOK=INTEGRATION_MOCK``, never a LIVE customer-provider call.
B14 is deliberately replaced with a failing probe: the managed path proves the
injection is live while the BYOK path must complete with zero B14 calls.
"""
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
        migrations = Path(__file__).resolve().parents[1] / "migrations"
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


class FailingCatalog:
    def __init__(self):
        self.calls = 0

    def _refuse(self):
        self.calls += 1
        raise AssertionError("B14 catalog read on BYOK_DIRECT")

    async def list_registered_models(self):
        self._refuse()

    async def list_selectable_models(self):
        self._refuse()


class FailingPolicyStore:
    def __init__(self):
        self.calls = 0

    async def snapshot(self, workspace_id):
        self.calls += 1
        raise AssertionError("B14 model policy read on BYOK_DIRECT")


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
            client.cookies.set(SESSION_COOKIE, create_session_token(settings(), uid))
        return await client.request(
            method, path, json=json_body, headers=request_headers
        )


def chat_payload(*, content="안녕하세요", conversation_id=None):
    payload = {
        "messages": [{"role": "user", "content": content}],
        "custom": {"provider": PROVIDER_ID, "model": MODEL_ID},
    }
    if conversation_id is not None:
        payload["conversation_id"] = conversation_id
    return payload


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


# ---------------------------------------------------------------------------
# Chat BYOK_DIRECT: request -> provider -> real conversation save/restore
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_stream_turn_saves_and_restores_real_d1_history():
    app, d1, _, _, recorder = build_app()
    await save_key(app, OWNER, CUSTOM_KEY)

    first = await request(
        app, "POST", "/api/chat", uid=OWNER, json_body=chat_payload(content="첫 번째 질문")
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["answer"] == DEFAULT_ANSWER
    assert "provider" not in body and "model" not in body
    conversation_id = body["conversation_id"]
    assert conversation_id.startswith("chat_")

    stored = d1.conversations()
    assert len(stored) == 1
    assert stored[0]["id"] == conversation_id
    assert stored[0]["user_id"] == OWNER
    assert stored[0]["product_scope"] == PRODUCT_SCOPE_CHAT
    assert d1.messages(conversation_id) == [
        {"role": "user", "content": "첫 번째 질문", "sequence_number": 0},
        {"role": "assistant", "content": DEFAULT_ANSWER, "sequence_number": 1},
    ]

    assert str(recorder.requests[0].url) == PROVIDER_URL
    assert recorder.authorization(0) == "Bearer " + CUSTOM_KEY
    sent = recorder.sent(0)
    assert sent["model"] == "beam-free"
    assert sent["messages"][0]["role"] == "system"
    assert PADIEM_IDENTITY_INSTRUCTION in sent["messages"][0]["content"]
    assert sent["messages"][1:] == [{"role": "user", "content": "첫 번째 질문"}]

    second = await request(
        app, "POST", "/api/chat", uid=OWNER,
        json_body=chat_payload(content="두 번째 질문", conversation_id=conversation_id),
    )
    assert second.status_code == 200, second.text
    assert second.json()["conversation_id"] == conversation_id

    # The browser sent only the new turn; the previous turns came from D1.
    assert recorder.sent(1)["messages"][1:] == [
        {"role": "user", "content": "첫 번째 질문"},
        {"role": "assistant", "content": DEFAULT_ANSWER},
        {"role": "user", "content": "두 번째 질문"},
    ]
    assert [row["role"] for row in d1.messages(conversation_id)] == [
        "user", "assistant", "user", "assistant",
    ]
    assert app.state.b14_client.calls == 0


@pytest.mark.asyncio
async def test_stream_turn_persists_and_restores_real_d1_history():
    app, d1, _, _, recorder = build_app()
    await save_key(app, OWNER, CUSTOM_KEY)

    first = await request(
        app, "POST", "/api/chat/stream", uid=OWNER,
        json_body=chat_payload(content="스트림 첫 질문"),
    )
    assert first.status_code == 200, first.text
    events = sse_events(first.text)
    assert [name for name, _ in events] == ["delta", "done"]
    assert events[0][1] == {"delta": DEFAULT_ANSWER}
    conversation_id = events[1][1]["conversation_id"]
    assert conversation_id.startswith("chat_")

    second = await request(
        app, "POST", "/api/chat/stream", uid=OWNER,
        json_body=chat_payload(content="스트림 둘째 질문", conversation_id=conversation_id),
    )
    assert second.status_code == 200, second.text
    assert recorder.sent(1)["messages"][1:] == [
        {"role": "user", "content": "스트림 첫 질문"},
        {"role": "assistant", "content": DEFAULT_ANSWER},
        {"role": "user", "content": "스트림 둘째 질문"},
    ]
    assert len(d1.messages(conversation_id)) == 4
    assert app.state.b14_client.calls == 0


# ---------------------------------------------------------------------------
# B14 failure injection: managed path fails, BYOK never reaches it
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_managed_negative_control_fails_on_injected_b14_failure():
    app, d1, _, _, _ = build_app()

    response = await request(
        app, "POST", "/api/chat", uid=OWNER,
        json_body={"messages": [{"role": "user", "content": "일반 질문"}], "tier": "free"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "b14_injected_failure"
    assert app.state.b14_client.complete_calls == 1
    assert app.state.b14_client.stream_calls == 0
    assert d1.conversations() == []


@pytest.mark.asyncio
async def test_byok_completes_with_failing_b14_client_router_and_catalog(monkeypatch):
    app, _, _, _, recorder = build_app()
    catalog = FailingCatalog()
    policy = FailingPolicyStore()
    app.state.b14_catalog_source = catalog
    app.state.central_model_policy_store = policy
    router_calls = {"resolve": 0, "guard": 0}

    def _router_entered(*args, **kwargs):
        router_calls["resolve"] += 1
        raise AssertionError("B14 router entered on BYOK_DIRECT")

    async def _guard_entered(*args, **kwargs):
        router_calls["guard"] += 1
        raise AssertionError("B14 dispatch guard entered on BYOK_DIRECT")

    monkeypatch.setattr(chat_routes, "resolve_request_model_policy", _router_entered)
    monkeypatch.setattr(chat_routes, "create_guard_from_request", _guard_entered)

    await save_key(app, OWNER, CUSTOM_KEY)

    response = await request(
        app, "POST", "/api/chat", uid=OWNER, json_body=chat_payload(content="B14 없이 답변")
    )
    assert response.status_code == 200, response.text
    assert response.json()["answer"] == DEFAULT_ANSWER
    assert len(recorder.requests) == 1
    assert app.state.b14_client.calls == 0
    assert router_calls == {"resolve": 0, "guard": 0}
    assert catalog.calls == 0
    assert policy.calls == 0

    stream = await request(
        app, "POST", "/api/chat/stream", uid=OWNER,
        json_body=chat_payload(content="B14 없이 스트림"),
    )
    assert stream.status_code == 200, stream.text
    assert sse_events(stream.text)[0][1] == {"delta": DEFAULT_ANSWER}
    assert len(recorder.requests) == 2
    assert app.state.b14_client.calls == 0
    assert router_calls == {"resolve": 0, "guard": 0}


# ---------------------------------------------------------------------------
# Tenant isolation, key rotation/deletion, provider failure side effects
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_keys_conversations_and_sessions_are_tenant_isolated():
    app, d1, _, _, recorder = build_app()
    await save_key(app, OWNER, CUSTOM_KEY)
    await save_key(app, OTHER, OTHER_KEY)

    owner_turn = await request(
        app, "POST", "/api/chat", uid=OWNER, json_body=chat_payload(content="소유자 질문")
    )
    other_turn = await request(
        app, "POST", "/api/chat", uid=OTHER, json_body=chat_payload(content="다른 고객 질문")
    )
    assert owner_turn.status_code == 200 and other_turn.status_code == 200
    owner_cid = owner_turn.json()["conversation_id"]
    other_cid = other_turn.json()["conversation_id"]
    assert owner_cid != other_cid

    assert recorder.authorization(0) == "Bearer " + CUSTOM_KEY
    assert recorder.authorization(1) == "Bearer " + OTHER_KEY
    assert {row["id"]: row["user_id"] for row in d1.conversations()} == {
        owner_cid: OWNER,
        other_cid: OTHER,
    }
    assert CUSTOM_KEY.encode() not in b"".join(
        value.encode() for value in d1.sealed_credentials()
    )

    owner_list = await request(app, "GET", "/api/conversations", uid=OWNER)
    other_list = await request(app, "GET", "/api/conversations", uid=OTHER)
    assert [item["id"] for item in owner_list.json()["conversations"]] == [owner_cid]
    assert [item["id"] for item in other_list.json()["conversations"]] == [other_cid]

    leaked_read = await request(
        app, "GET", f"/api/conversations/{owner_cid}", uid=OTHER
    )
    assert leaked_read.status_code == 404

    before = len(recorder.requests)
    leaked_continue = await request(
        app, "POST", "/api/chat", uid=OTHER,
        json_body=chat_payload(content="남의 대화 이어쓰기", conversation_id=owner_cid),
    )
    assert leaked_continue.status_code == 404
    assert len(recorder.requests) == before

    owner_status = await request(app, "GET", "/api/chat/custom/credential", uid=OWNER)
    other_status = await request(app, "GET", "/api/chat/custom/credential", uid=OTHER)
    assert owner_status.json()["credentials"][0]["key_last4"] == CUSTOM_KEY[-4:]
    assert other_status.json()["credentials"][0]["key_last4"] == OTHER_KEY[-4:]
    assert CUSTOM_KEY not in owner_status.text
    assert OTHER_KEY not in other_status.text
    assert app.state.b14_client.calls == 0


@pytest.mark.asyncio
async def test_key_rotation_and_deletion_apply_to_the_next_turn():
    app, d1, _, _, recorder = build_app()
    await save_key(app, OWNER, CUSTOM_KEY)

    first = await request(
        app, "POST", "/api/chat", uid=OWNER, json_body=chat_payload(content="회전 전")
    )
    assert first.status_code == 200
    assert recorder.authorization(0) == "Bearer " + CUSTOM_KEY

    rotated = await save_key(app, OWNER, ROTATED_KEY)
    assert rotated.json()["credential"]["key_last4"] == ROTATED_KEY[-4:]

    second = await request(
        app, "POST", "/api/chat", uid=OWNER, json_body=chat_payload(content="회전 후")
    )
    assert second.status_code == 200
    assert recorder.authorization(1) == "Bearer " + ROTATED_KEY

    deleted = await request(
        app, "DELETE", f"/api/chat/custom/credential?provider={PROVIDER_ID}", uid=OWNER
    )
    assert deleted.status_code == 200
    assert deleted.json() == {"ok": True, "deleted": True, "provider": PROVIDER_ID}

    before = len(recorder.requests)
    conversations_before = len(d1.conversations())
    refused = await request(
        app, "POST", "/api/chat", uid=OWNER, json_body=chat_payload(content="삭제 후")
    )
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "custom_credential_required"
    assert len(recorder.requests) == before
    assert len(d1.conversations()) == conversations_before
    assert app.state.b14_client.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider_status", "expected_status", "code"),
    [
        (429, 429, "custom_provider_rate_limited"),
        (500, 502, "custom_provider_unavailable"),
    ],
)
async def test_provider_failures_leave_no_conversation_and_no_vendor_leak(
    provider_status, expected_status, code
):
    recorder = ProviderRecorder(
        lambda request: httpx.Response(provider_status, json={"error": "vendor-detail"})
    )
    app, d1, _, _, _ = build_app(recorder=recorder)
    await save_key(app, OWNER, CUSTOM_KEY)

    response = await request(
        app, "POST", "/api/chat", uid=OWNER, json_body=chat_payload(content="공급사 오류")
    )

    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == code
    assert "vendor" not in response.text
    assert d1.conversations() == []
    assert app.state.b14_client.calls == 0


@pytest.mark.asyncio
async def test_other_tenant_keeps_working_after_owner_key_deletion():
    app, _, _, _, recorder = build_app()
    await save_key(app, OWNER, CUSTOM_KEY)
    await save_key(app, OTHER, OTHER_KEY)

    await request(
        app, "DELETE", f"/api/chat/custom/credential?provider={PROVIDER_ID}", uid=OWNER
    )
    response = await request(
        app, "POST", "/api/chat", uid=OTHER, json_body=chat_payload(content="다른 고객")
    )

    assert response.status_code == 200
    assert recorder.authorization(0) == "Bearer " + OTHER_KEY
    assert app.state.b14_client.calls == 0
