"""#5121 PADIEM Custom (BYOK): owner-scoped keys and a B14-independent Chat path.

The custom path must:
* store only a sealed customer key, scoped to the canonical session user,
* execute the explicitly selected provider/model directly,
* never touch the B14 client, router, registry, default/fallback policy or
  platform secret store,
* persist and restore the conversation through the existing Chat history.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.byok_client import CustomProviderClient
from app.byok_credentials import D1CustomProviderCredentialStore
from app.b14_client import PADIEM_IDENTITY_INSTRUCTION
from app.config import Settings
from app.history import PRODUCT_SCOPE_CHAT
from app.main import create_app

SESSION_SECRET = "byok-5121-session-secret-not-a-real-credential"
CUSTOM_KEY_SECRET = "byok-5121-custom-key-secret-not-a-real-credential"
CUSTOM_KEY = "sk-customer-owned-5121-key-AAAA1111"
ROTATED_KEY = "sk-customer-owned-5121-key-BBBB2222"
OWNER = "usr_" + "a" * 32
OTHER = "usr_" + "b" * 32
PROVIDER_ID = "opencode-go"
MODEL_ID = "opencode-go/beam-free"
ORIGIN = "https://chat.example.test"


def settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url=ORIGIN,
        google_client_id="5121-client.apps.googleusercontent.com",
        google_client_secret="unit-test-google-secret",
        session_secret=SESSION_SECRET,
        custom_key_secret=CUSTOM_KEY_SECRET,
        session_max_age_seconds=3600,
    )


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

    async def all(self):
        cursor = self.conn.execute(self.query, self.parameters)
        rows = [dict(row) for row in cursor.fetchall()]
        self.conn.commit()
        return rows


class SQLiteD1:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            "CREATE TABLE users(id TEXT PRIMARY KEY);"
            f"INSERT INTO users(id) VALUES('{OWNER}'),('{OTHER}');"
        )
        sql = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "053_chat_custom_provider_credentials.sql"
        )
        self.conn.executescript(sql.read_text(encoding="utf-8"))

    def prepare(self, query):
        return Statement(self.conn, query)

    def sealed_values(self):
        return [
            row[0]
            for row in self.conn.execute(
                "SELECT sealed_credential FROM chat_custom_provider_credentials"
            )
        ]


class FakeAuthenticatedCipher:
    def random_bytes(self, size):
        assert size == 12
        return b"x" * 12

    async def encrypt(self, *, key, iv, plaintext, additional_data):
        tag = hashlib.sha256(key + iv + additional_data).digest()
        return tag + bytes(x ^ tag[i % len(tag)] for i, x in enumerate(plaintext))

    async def decrypt(self, *, key, iv, ciphertext, additional_data):
        tag = hashlib.sha256(key + iv + additional_data).digest()
        if ciphertext[:32] != tag:
            raise ValueError("AAD mismatch")
        return bytes(x ^ tag[i % len(tag)] for i, x in enumerate(ciphertext[32:]))


class MemoryHistoryStore:
    def __init__(self):
        self.users = set()
        self.conversations = {}
        self.counter = 0

    def add_user(self, user_id):
        self.users.add(user_id)

    async def get_user(self, user_id):
        return object() if user_id in self.users else None

    async def get_conversation(self, user_id, conversation_id, *, product_scope):
        row = self.conversations.get(conversation_id)
        if not row or row["user_id"] != user_id or row["product_scope"] != product_scope:
            return None
        return {
            "id": row["id"],
            "title": row["title"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "messages": [dict(message) for message in row["messages"]],
        }

    async def append_exchange(
        self,
        user_id,
        conversation_id,
        user_text,
        assistant_text,
        project_id=None,
        *,
        product_scope,
    ):
        from app.history import HistoryForbidden

        if conversation_id is None:
            self.counter += 1
            conversation_id = "chat_" + f"{self.counter:032x}"
            self.conversations[conversation_id] = {
                "id": conversation_id,
                "user_id": user_id,
                "title": user_text[:80],
                "product_scope": product_scope,
                "project_id": project_id,
                "created_at": "2026-10-19T00:00:00Z",
                "updated_at": "2026-10-19T00:00:00Z",
                "messages": [],
            }
        row = self.conversations.get(conversation_id)
        if not row or row["user_id"] != user_id or row["product_scope"] != product_scope:
            raise HistoryForbidden()
        row["messages"].extend(
            [
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": assistant_text},
            ]
        )
        return conversation_id


class B14Bomb:
    """Any attribute access means the B14-managed path was entered."""

    touches = 0

    def __getattr__(self, name):
        type(self).touches += 1
        raise AssertionError(f"B14 client touched on BYOK_DIRECT: {name}")


class ProviderRecorder:
    def __init__(self, handler=None):
        self.requests = []
        default = handler or (
            lambda request: httpx.Response(
                200,
                json={
                    "model": "beam-free",
                    "choices": [{"message": {"content": "custom 답변"}}],
                },
            )
        )
        self.transport = httpx.MockTransport(self._handle)
        self._handler = default

    def _handle(self, request):
        self.requests.append(request)
        return self._handler(request)


def build_app(store=None, recorder=None, d1=None):
    history = MemoryHistoryStore()
    history.add_user(OWNER)
    history.add_user(OTHER)
    if d1 is None:
        d1 = SQLiteD1()
    credential_store = store or D1CustomProviderCredentialStore(
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
    app.state.b14_client = B14Bomb()
    app.state.b14_catalog_source = B14Bomb()
    app.state.usage_gate_enforced = False
    B14Bomb.touches = 0
    return app, history, credential_store, recorder, d1


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


def sse_events(text):
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


# ---------------------------------------------------------------------------
# Store contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_seals_rotates_and_isolates_owner_keys():
    d1 = SQLiteD1()
    store = D1CustomProviderCredentialStore(
        d1,
        key_secret=CUSTOM_KEY_SECRET,
        session_secret=SESSION_SECRET,
        cipher=FakeAuthenticatedCipher(),
    )

    saved = await store.save(user_id=OWNER, provider_id=PROVIDER_ID, api_key=CUSTOM_KEY, now=100)
    assert saved["key_last4"] == CUSTOM_KEY[-4:]
    sealed = d1.sealed_values()
    assert CUSTOM_KEY not in sealed[0]
    assert CUSTOM_KEY.encode() not in sealed[0].encode()
    assert await store.api_key(OWNER, PROVIDER_ID) == CUSTOM_KEY

    # Owner isolation: another canonical user never sees or removes this key.
    assert await store.api_key(OTHER, PROVIDER_ID) is None
    assert await store.status(OTHER) == []
    await store.delete(OTHER, PROVIDER_ID)
    assert await store.api_key(OWNER, PROVIDER_ID) == CUSTOM_KEY

    rotated = await store.save(user_id=OWNER, provider_id=PROVIDER_ID, api_key=ROTATED_KEY, now=200)
    assert rotated["key_last4"] == ROTATED_KEY[-4:]
    assert await store.api_key(OWNER, PROVIDER_ID) == ROTATED_KEY
    status = await store.status(OWNER)
    assert status == [
        {
            "provider": PROVIDER_ID,
            "key_last4": ROTATED_KEY[-4:],
            "created_at": 100,
            "updated_at": 200,
        }
    ]

    assert await store.delete(OWNER, PROVIDER_ID) is True
    assert await store.api_key(OWNER, PROVIDER_ID) is None
    assert await store.status(OWNER) == []
    # Unknown provider is never stored or looked up.
    with pytest.raises(ValueError):
        await store.save(user_id=OWNER, provider_id="unknown", api_key=CUSTOM_KEY)


# ---------------------------------------------------------------------------
# Credential routes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_credential_routes_are_session_scoped_and_metadata_only():
    app, *_ = build_app()

    unauthorized = await request(app, "PUT", "/api/chat/custom/credential", json_body={
        "provider": PROVIDER_ID, "api_key": CUSTOM_KEY,
    })
    assert unauthorized.status_code == 401

    saved = await request(
        app, "PUT", "/api/chat/custom/credential", uid=OWNER,
        json_body={"provider": PROVIDER_ID, "api_key": CUSTOM_KEY},
    )
    assert saved.status_code == 200
    body = saved.json()
    assert CUSTOM_KEY not in saved.text
    assert body["credential"]["key_last4"] == CUSTOM_KEY[-4:]
    assert set(body["credential"]) == {"provider", "key_last4", "updated_at"}

    status = await request(app, "GET", "/api/chat/custom/credential", uid=OTHER)
    assert status.status_code == 200
    assert status.json()["credentials"] == []

    status = await request(app, "GET", "/api/chat/custom/credential", uid=OWNER)
    credentials = status.json()["credentials"]
    assert len(credentials) == 1
    assert credentials[0]["key_last4"] == CUSTOM_KEY[-4:]
    assert CUSTOM_KEY not in status.text

    unsupported = await request(
        app, "PUT", "/api/chat/custom/credential", uid=OWNER,
        json_body={"provider": "unknown", "api_key": CUSTOM_KEY},
    )
    assert unsupported.status_code == 422

    rotated = await request(
        app, "PUT", "/api/chat/custom/credential", uid=OWNER,
        json_body={"provider": PROVIDER_ID, "api_key": ROTATED_KEY},
    )
    assert rotated.status_code == 200
    assert rotated.json()["credential"]["key_last4"] == ROTATED_KEY[-4:]

    deleted = await request(
        app, "DELETE", f"/api/chat/custom/credential?provider={PROVIDER_ID}", uid=OWNER
    )
    assert deleted.status_code == 200
    assert deleted.json() == {"ok": True, "deleted": True, "provider": PROVIDER_ID}
    status = await request(app, "GET", "/api/chat/custom/credential", uid=OWNER)
    assert status.json()["credentials"] == []


# ---------------------------------------------------------------------------
# Chat BYOK_DIRECT execution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_custom_executes_direct_provider_without_b14():
    app, history, credential_store, recorder, _ = build_app()
    await credential_store.save(user_id=OWNER, provider_id=PROVIDER_ID, api_key=CUSTOM_KEY)

    response = await request(app, "POST", "/api/chat", uid=OWNER, json_body=chat_payload())
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer"] == "custom 답변"
    assert "model" not in payload and "provider" not in payload
    assert payload["conversation_id"].startswith("chat_")
    assert B14Bomb.touches == 0

    assert len(recorder.requests) == 1
    wire = recorder.requests[0]
    assert str(wire.url) == "https://opencode.ai/inference/go/v1/chat/completions"
    assert wire.headers["authorization"] == "Bearer " + CUSTOM_KEY
    assert wire.headers["x-opencode-session"].startswith("chat_")
    sent = json.loads(wire.content)
    assert sent["model"] == "beam-free"
    assert sent["messages"][0]["role"] == "system"
    assert PADIEM_IDENTITY_INSTRUCTION in sent["messages"][0]["content"]
    assert sent["messages"][1] == {"role": "user", "content": "안녕하세요"}

    saved = history.conversations[payload["conversation_id"]]
    assert [m["role"] for m in saved["messages"]] == ["user", "assistant"]
    assert saved["messages"][1]["content"] == "custom 답변"


@pytest.mark.asyncio
async def test_chat_custom_stream_persists_and_restores_server_history():
    app, history, credential_store, recorder, _ = build_app()
    await credential_store.save(user_id=OWNER, provider_id=PROVIDER_ID, api_key=CUSTOM_KEY)

    first = await request(
        app, "POST", "/api/chat/stream", uid=OWNER,
        json_body=chat_payload(content="첫 번째 질문"),
    )
    assert first.status_code == 200, first.text
    events = sse_events(first.text)
    assert [name for name, _ in events] == ["delta", "done"]
    assert events[0][1] == {"delta": "custom 답변"}
    conversation_id = events[1][1]["conversation_id"]
    assert conversation_id.startswith("chat_")
    assert B14Bomb.touches == 0

    second = await request(
        app, "POST", "/api/chat/stream", uid=OWNER,
        json_body=chat_payload(content="두 번째 질문", conversation_id=conversation_id),
    )
    assert second.status_code == 200, second.text
    assert B14Bomb.touches == 0

    second_messages = json.loads(recorder.requests[1].content)["messages"]
    assert second_messages[1:] == [
        {"role": "user", "content": "첫 번째 질문"},
        {"role": "assistant", "content": "custom 답변"},
        {"role": "user", "content": "두 번째 질문"},
    ]
    saved = history.conversations[conversation_id]
    assert len(saved["messages"]) == 4


@pytest.mark.asyncio
async def test_chat_custom_rejects_missing_key_selection_and_mixed_requests():
    app, _, _, recorder, _ = build_app()

    missing = await request(app, "POST", "/api/chat", uid=OWNER, json_body=chat_payload())
    assert missing.status_code == 409
    assert missing.json()["error"]["code"] == "custom_credential_required"

    anonymous = await request(app, "POST", "/api/chat", json_body=chat_payload())
    assert anonymous.status_code == 401
    assert anonymous.json()["error"]["code"] == "unauthorized"

    unknown = await request(app, "POST", "/api/chat", uid=OWNER, json_body={
        "messages": [{"role": "user", "content": "hi"}],
        "custom": {"provider": PROVIDER_ID, "model": "opencode-go/not-a-model"},
    })
    assert unknown.status_code == 422
    assert unknown.json()["error"]["code"] == "custom_provider_unsupported"

    mixed = await request(app, "POST", "/api/chat", uid=OWNER, json_body={
        **chat_payload(),
        "tier": "free",
    })
    assert mixed.status_code == 422

    with_tool = await request(app, "POST", "/api/chat", uid=OWNER, json_body={
        **chat_payload(),
        "tool": "deep_research",
        "tool_input": "검색",
    })
    assert with_tool.status_code == 422
    assert with_tool.json()["error"]["message"] == "PADIEM Custom은 현재 텍스트 대화만 지원합니다."

    assert recorder.requests == []
    assert B14Bomb.touches == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "body", "expected_status", "code"),
    [
        (401, {"error": "vendor-auth-detail"}, 502, "custom_provider_auth_failed"),
        (403, {"error": "vendor-forbidden"}, 502, "custom_provider_auth_failed"),
        (429, {"error": "vendor-rate-detail"}, 429, "custom_provider_rate_limited"),
        (500, {"error": "vendor-server-detail"}, 502, "custom_provider_unavailable"),
        (418, {"error": "vendor-teapot"}, 502, "custom_provider_rejected"),
    ],
)
async def test_chat_custom_maps_provider_failures_without_vendor_leak(
    status, body, expected_status, code
):
    recorder = ProviderRecorder(lambda request: httpx.Response(status, json=body))
    app, _, credential_store, _, _ = build_app(recorder=recorder)
    await credential_store.save(user_id=OWNER, provider_id=PROVIDER_ID, api_key=CUSTOM_KEY)

    response = await request(app, "POST", "/api/chat", uid=OWNER, json_body=chat_payload())
    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == code
    assert "vendor" not in response.text
    assert B14Bomb.touches == 0


@pytest.mark.asyncio
async def test_chat_custom_maps_timeout_and_unreachable():
    def timeout_handler(_request):
        raise httpx.ReadTimeout("provider timeout sentinel")

    app, _, credential_store, _, _ = build_app(
        recorder=ProviderRecorder(timeout_handler)
    )
    await credential_store.save(user_id=OWNER, provider_id=PROVIDER_ID, api_key=CUSTOM_KEY)
    response = await request(app, "POST", "/api/chat", uid=OWNER, json_body=chat_payload())
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "custom_provider_timeout"
    assert "sentinel" not in response.text

    def unreachable_handler(_request):
        raise httpx.ConnectError("connect sentinel")

    app, _, credential_store, _, _ = build_app(
        recorder=ProviderRecorder(unreachable_handler)
    )
    await credential_store.save(user_id=OWNER, provider_id=PROVIDER_ID, api_key=CUSTOM_KEY)
    response = await request(app, "POST", "/api/chat", uid=OWNER, json_body=chat_payload())
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "custom_provider_unreachable"
    assert "sentinel" not in response.text


@pytest.mark.asyncio
async def test_chat_custom_rejects_unexpected_wire_model_and_malformed_body():
    mismatch = ProviderRecorder(
        lambda request: httpx.Response(
            200,
            json={"model": "some-other-model", "choices": [{"message": {"content": "x"}}]},
        )
    )
    app, _, credential_store, _, _ = build_app(recorder=mismatch)
    await credential_store.save(user_id=OWNER, provider_id=PROVIDER_ID, api_key=CUSTOM_KEY)
    response = await request(app, "POST", "/api/chat", uid=OWNER, json_body=chat_payload())
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "malformed_custom_provider_response"

    malformed = ProviderRecorder(lambda request: httpx.Response(200, content=b"not-json"))
    app, _, credential_store, _, _ = build_app(recorder=malformed)
    await credential_store.save(user_id=OWNER, provider_id=PROVIDER_ID, api_key=CUSTOM_KEY)
    response = await request(app, "POST", "/api/chat", uid=OWNER, json_body=chat_payload())
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "malformed_custom_provider_response"


@pytest.mark.asyncio
async def test_expired_session_cannot_use_custom_path():
    app, _, credential_store, recorder, _ = build_app()
    await credential_store.save(user_id=OWNER, provider_id=PROVIDER_ID, api_key=CUSTOM_KEY)
    expired = SESSION_COOKIE + "=" + create_session_token(settings(), OWNER, now=1)
    response = await request(
        app, "POST", "/api/chat", json_body=chat_payload(),
        headers={"Cookie": expired},
    )
    # The guard only sees a cookie; it passes same-origin, then the route finds
    # no valid session and refuses before any key lookup or provider call.
    assert response.status_code == 401
    assert recorder.requests == []
    assert B14Bomb.touches == 0
