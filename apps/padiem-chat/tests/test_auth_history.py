from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from app.auth import (
    GOOGLE_AUTH_URL,
    GOOGLE_TOKEN_URL,
    GOOGLE_USERINFO_URL,
    OAUTH_STATE_COOKIE,
    SESSION_COOKIE,
    create_oauth_state,
    create_session_token,
    decode_session_token,
    verify_oauth_state,
)
from app.config import ConfigError, Settings
from app.history import D1HistoryStore, HistoryForbidden, UserProfile
from app.main import create_app

SESSION_SECRET = "phase9-session-secret-not-a-real-credential-000000"


def google_settings(**overrides):
    values = dict(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="phase9-client.apps.googleusercontent.com",
        google_client_secret="unit-test-google-secret",
        session_secret=SESSION_SECRET,
        session_max_age_seconds=3600,
    )
    values.update(overrides)
    return Settings.from_values(**values)


class MemoryHistoryStore:
    def __init__(self):
        self.users = {}
        self.conversations = {}
        self.counter = 0

    async def upsert_google_user(self, subject, email, name, picture):
        uid = "usr_" + subject.replace("-", "")[:32].ljust(32, "0")
        profile = UserProfile(uid, email, name or email.split("@", 1)[0], picture)
        self.users[uid] = profile
        return profile

    async def get_user(self, user_id):
        return self.users.get(user_id)

    async def list_conversations(self, user_id, limit=30):
        rows = [c for c in self.conversations.values() if c["user_id"] == user_id]
        rows.sort(key=lambda row: row["updated_at"], reverse=True)
        return [{k: c[k] for k in ("id", "title", "created_at", "updated_at")} for c in rows[:limit]]

    async def get_conversation(self, user_id, conversation_id):
        row = self.conversations.get(conversation_id)
        if not row or row["user_id"] != user_id:
            return None
        return {
            "id": row["id"], "title": row["title"], "created_at": row["created_at"], "updated_at": row["updated_at"],
            "messages": [{"role": m["role"], "content": m["content"]} for m in row["messages"]],
        }

    async def delete_conversation(self, user_id, conversation_id):
        row = self.conversations.get(conversation_id)
        if not row or row["user_id"] != user_id:
            return False
        del self.conversations[conversation_id]
        return True

    async def append_exchange(self, user_id, conversation_id, user_text, assistant_text):
        if conversation_id is None:
            self.counter += 1
            conversation_id = "chat_" + f"{self.counter:032x}"
            self.conversations[conversation_id] = {
                "id": conversation_id, "user_id": user_id, "title": user_text[:80],
                "created_at": f"2026-08-25T00:00:{self.counter:02d}Z",
                "updated_at": f"2026-08-25T00:00:{self.counter:02d}Z", "messages": [],
            }
        row = self.conversations.get(conversation_id)
        if not row or row["user_id"] != user_id:
            raise HistoryForbidden()
        row["messages"].extend([
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": assistant_text},
        ])
        self.counter += 1
        row["updated_at"] = f"2026-08-25T00:01:{self.counter:02d}Z"
        return conversation_id


async def add_test_user(store: MemoryHistoryStore, subject="1234567890", email="user@example.test", name="테스트 사용자"):
    return await store.upsert_google_user(subject, email, name, "")


def png_attachment():
    raw = b"\x89PNG\r\n\x1a\nphase-nine"
    return [{
        "type": "image",
        "name": "photo.png",
        "media_type": "image/png",
        "base64": base64.b64encode(raw).decode("ascii"),
    }]


def test_auth_defaults_off_and_google_mode_validation():
    defaults = Settings.from_values()
    assert defaults.auth_mode == "off"
    assert defaults.public_base_url is None
    assert defaults.session_secret is None
    for kwargs in [
        {"auth_mode": "google"},
        {"auth_mode": "google", "public_base_url": "http://chat.example.test", "google_client_id": "id", "google_client_secret": "secret", "session_secret": SESSION_SECRET},
        {"auth_mode": "google", "public_base_url": "https://chat.example.test/path", "google_client_id": "id", "google_client_secret": "secret", "session_secret": SESSION_SECRET},
        {"auth_mode": "google", "public_base_url": "https://chat.example.test", "google_client_id": "id", "google_client_secret": "secret", "session_secret": "short"},
    ]:
        with pytest.raises(ConfigError):
            Settings.from_values(**kwargs)
    configured = google_settings()
    assert configured.auth_mode == "google"
    assert "unit-test-google-secret" not in repr(configured)
    assert SESSION_SECRET not in repr(configured)


def test_signed_session_and_state_reject_tamper_and_expiry():
    settings = google_settings()
    token = create_session_token(settings, "usr_" + "a" * 32, now=100)
    assert decode_session_token(settings, token, now=101) == "usr_" + "a" * 32
    assert decode_session_token(settings, token + "x", now=101) is None
    assert decode_session_token(settings, token, now=3701) is None
    state, signed = create_oauth_state(settings, now=100)
    assert verify_oauth_state(settings, state, signed, now=101)
    assert not verify_oauth_state(settings, state + "x", signed, now=101)
    assert not verify_oauth_state(settings, state, signed, now=701)


@pytest.mark.asyncio
async def test_oauth_start_uses_exact_google_host_and_secure_state_cookie():
    store = MemoryHistoryStore()
    app = create_app(google_settings(), history_store=store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test", follow_redirects=False) as client:
        response = await client.get("/auth/google/start")
    assert response.status_code == 302
    assert response.headers["location"].startswith(GOOGLE_AUTH_URL + "?")
    assert "client_id=phase9-client.apps.googleusercontent.com" in response.headers["location"]
    cookie = response.headers["set-cookie"]
    assert OAUTH_STATE_COOKIE in cookie
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie


@pytest.mark.asyncio
async def test_callback_rejects_bad_state_before_any_google_call():
    calls = 0
    async def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(500)
    app = create_app(google_settings(), auth_transport=httpx.MockTransport(handler), history_store=MemoryHistoryStore())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test") as client:
        response = await client.get("/auth/google/callback?state=bad&code=code")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_oauth_state"
    assert calls == 0


@pytest.mark.asyncio
async def test_google_exchange_and_userinfo_use_fixed_endpoints_and_token_never_leaks():
    seen = []
    access_token = "opaque-test-access-token"
    async def handler(request):
        seen.append((str(request.url), request.method, request.content, dict(request.headers)))
        if str(request.url) == GOOGLE_TOKEN_URL:
            return httpx.Response(200, json={"access_token": access_token, "token_type": "Bearer", "expires_in": 3600})
        if str(request.url) == GOOGLE_USERINFO_URL:
            assert request.headers.get("Authorization") == f"Bearer {access_token}"
            return httpx.Response(200, json={"id": "1234567890", "email": "user@example.test", "verified_email": True, "name": "테스트 사용자", "picture": "https://images.example.test/u.png"})
        return httpx.Response(404)

    store = MemoryHistoryStore()
    app = create_app(google_settings(), auth_transport=httpx.MockTransport(handler), history_store=store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test", follow_redirects=False) as client:
        start = await client.get("/auth/google/start")
        assert start.status_code == 302
        state = httpx.URL(start.headers["location"]).params["state"]
        callback = await client.get(f"/auth/google/callback?state={state}&code=sample-code")
        assert callback.status_code == 302
        assert callback.headers["location"] == "/"
        status = await client.get("/api/auth/status")
    assert [item[0] for item in seen] == [GOOGLE_TOKEN_URL, GOOGLE_USERINFO_URL]
    assert status.json()["authenticated"] is True
    serialized = callback.text + json.dumps(status.json(), ensure_ascii=False) + callback.headers.get("set-cookie", "")
    assert access_token not in serialized
    assert SESSION_COOKIE in callback.headers["set-cookie"]
    assert all(access_token not in json.dumps(c, ensure_ascii=False) for c in store.conversations.values())


@pytest.mark.asyncio
async def test_logout_clears_session_cookie():
    store = MemoryHistoryStore()
    profile = await add_test_user(store)
    settings = google_settings()
    app = create_app(settings, history_store=store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test") as client:
        client.cookies.set(SESSION_COOKIE, create_session_token(settings, profile.id), domain="chat.example.test", path="/")
        response = await client.post("/api/auth/logout")
    assert response.status_code == 200
    assert SESSION_COOKIE in response.headers["set-cookie"]
    assert "Max-Age=0" in response.headers["set-cookie"]


@pytest.mark.asyncio
async def test_no_store_reports_not_ready_and_keeps_anonymous_chat():
    app = create_app(Settings.from_values())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        status = await client.get("/api/auth/status")
        chat = await client.post("/api/chat", json={"messages": [{"role": "user", "content": "안녕"}], "mode": "auto"})
    assert status.json() == {"ready": False, "authenticated": False, "history_ready": False, "user": None}
    assert chat.status_code == 200
    assert "conversation_id" not in chat.json()


@pytest.mark.asyncio
async def test_authenticated_chat_creates_and_appends_owner_scoped_history():
    store = MemoryHistoryStore()
    profile = await add_test_user(store)
    settings = google_settings()
    app = create_app(settings, history_store=store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test") as client:
        client.cookies.set(SESSION_COOKIE, create_session_token(settings, profile.id), domain="chat.example.test", path="/")
        first = await client.post("/api/chat", json={"messages": [{"role": "user", "content": "첫 질문"}], "mode": "auto"})
        cid = first.json()["conversation_id"]
        second_messages = [
            {"role": "user", "content": "첫 질문"},
            {"role": "assistant", "content": first.json()["answer"]},
            {"role": "user", "content": "두 번째 질문"},
        ]
        second = await client.post("/api/chat", json={"messages": second_messages, "mode": "auto", "conversation_id": cid})
        detail = await client.get(f"/api/conversations/{cid}")
        recent = await client.get("/api/conversations")
    assert first.status_code == 200 and second.status_code == 200
    assert second.json()["conversation_id"] == cid
    stored = detail.json()["conversation"]["messages"]
    assert [m["role"] for m in stored] == ["user", "assistant", "user", "assistant"]
    assert stored[0]["content"] == "첫 질문" and stored[2]["content"] == "두 번째 질문"
    assert recent.json()["conversations"][0]["id"] == cid


@pytest.mark.asyncio
async def test_cross_user_conversation_is_rejected_before_answer_and_anonymous_id_is_ignored():
    store = MemoryHistoryStore()
    owner = await add_test_user(store, "1111111111", "owner@example.test", "owner")
    other = await add_test_user(store, "2222222222", "other@example.test", "other")
    settings = google_settings()
    cid = await store.append_exchange(owner.id, None, "owner question", "owner answer")
    app = create_app(settings, history_store=store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test") as client:
        client.cookies.set(SESSION_COOKIE, create_session_token(settings, other.id), domain="chat.example.test", path="/")
        denied = await client.post("/api/chat", json={"messages": [{"role": "user", "content": "침범"}], "mode": "auto", "conversation_id": cid})
    assert denied.status_code == 404
    assert len(store.conversations[cid]["messages"]) == 2

    anon_app = create_app(Settings.from_values(), history_store=store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=anon_app), base_url="http://test") as client:
        anonymous = await client.post("/api/chat", json={"messages": [{"role": "user", "content": "익명"}], "mode": "auto", "conversation_id": cid})
    assert anonymous.status_code == 200
    assert "conversation_id" not in anonymous.json()
    assert len(store.conversations[cid]["messages"]) == 2


@pytest.mark.asyncio
async def test_conversation_delete_is_owner_scoped_and_bounded():
    store = MemoryHistoryStore()
    owner = await add_test_user(store, "3333333333", "owner-delete@example.test", "owner")
    other = await add_test_user(store, "4444444444", "other-delete@example.test", "other")
    cid = await store.append_exchange(owner.id, None, "삭제할 대화", "보존된 답변")
    settings = google_settings()
    app = create_app(settings, history_store=store)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test") as client:
        client.cookies.set(SESSION_COOKIE, create_session_token(settings, other.id), domain="chat.example.test", path="/")
        foreign = await client.delete(f"/api/conversations/{cid}")
        malformed = await client.delete("/api/conversations/not-a-conversation")
    assert foreign.status_code == 404
    assert malformed.status_code == 404
    assert cid in store.conversations

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test") as client:
        client.cookies.set(SESSION_COOKIE, create_session_token(settings, owner.id), domain="chat.example.test", path="/")
        deleted = await client.delete(f"/api/conversations/{cid}")
        missing = await client.delete(f"/api/conversations/{cid}")
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True, "conversation_id": cid}
    assert missing.status_code == 404
    assert cid not in store.conversations


@pytest.mark.asyncio
async def test_failed_model_call_does_not_persist_and_image_base64_never_persists():
    store = MemoryHistoryStore()
    profile = await add_test_user(store)
    failing_settings = google_settings(runtime_mode="b14", b14_base_url="https://b14.example")
    async def fail_handler(request):
        return httpx.Response(500, json={"private": "not exposed"})
    fail_app = create_app(failing_settings, transport=httpx.MockTransport(fail_handler), history_store=store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=fail_app), base_url="https://chat.example.test") as client:
        client.cookies.set(SESSION_COOKIE, create_session_token(failing_settings, profile.id), domain="chat.example.test", path="/")
        failed = await client.post("/api/chat", json={"messages": [{"role": "user", "content": "실패"}], "mode": "auto"})
    assert failed.status_code == 502
    assert store.conversations == {}

    settings = google_settings()
    app = create_app(settings, history_store=store)
    attachment = png_attachment()
    secret_b64 = attachment[0]["base64"]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test") as client:
        client.cookies.set(SESSION_COOKIE, create_session_token(settings, profile.id), domain="chat.example.test", path="/")
        ok = await client.post("/api/chat", json={"messages": [{"role": "user", "content": "이 사진 설명"}], "mode": "auto", "attachments": attachment})
    assert ok.status_code == 200
    dumped = json.dumps(store.conversations, ensure_ascii=False)
    assert secret_b64 not in dumped
    assert "이 사진 설명" in dumped


class FakeStatement:
    def __init__(self, db, sql):
        self.db = db
        self.sql = sql
        self.values = ()
    def bind(self, *values):
        self.values = values
        self.db.bound.append((self.sql, values))
        return self
    async def run(self):
        if self.sql.startswith("SELECT id, title"):
            return {"results": []}
        return {"results": []}
    async def first(self):
        if self.sql.startswith("SELECT id FROM conversations WHERE id=? AND user_id=?"):
            return {"id": self.values[0]}
        return None


class FakeD1:
    def __init__(self):
        self.prepared = []
        self.bound = []
    def prepare(self, sql):
        self.prepared.append(sql)
        return FakeStatement(self, sql)


@pytest.mark.asyncio
async def test_d1_adapter_uses_prepared_bound_values_not_interpolation():
    db = FakeD1()
    store = D1HistoryStore(db)
    marker = "USER_VALUE_SHOULD_ONLY_BE_BOUND"
    await store.upsert_google_user("subject-1", "user@example.test", marker, "")
    await store.list_conversations("usr_fake")
    cid = "chat_" + "a" * 32
    assert await store.delete_conversation("usr_fake", cid) is True
    assert any(
        sql.startswith("DELETE FROM conversations WHERE id=? AND user_id=?") and values == (cid, "usr_fake")
        for sql, values in db.bound
    )
    assert db.prepared
    assert db.bound
    assert all(marker not in sql for sql in db.prepared)
    assert any(marker in values for _, values in db.bound)


def test_auth_history_frontend_contract_and_phase1_css_unchanged():
    root = Path(__file__).resolve().parents[1]
    html = (root / "static/index.html").read_text(encoding="utf-8")
    js = (root / "static/app.js").read_text(encoding="utf-8")
    assert 'id="loginButton"' in html
    assert 'id="historySection"' in html and 'id="historyList"' in html
    assert 'href="./history.css"' in html
    assert 'fetch("/api/auth/status"' in js
    assert 'fetch("/api/conversations"' in js
    assert 'method: "DELETE"' in js
    assert "삭제한 대화는 되돌릴 수 없습니다." in js
    assert "history-delete" in js
    assert "conversationId" in js and "payload.conversation_id" in js
    assert 'window.location.assign("/auth/google/start")' in js
    assert "access_token" not in js
    assert "GOOGLE_CLIENT" not in html and "GOOGLE_CLIENT" not in js
    repo = root.parents[1]
    assert (root / "static/styles.css").read_bytes() == (repo / "reference/business-62-padiem-chat-v1/styles.css").read_bytes()
