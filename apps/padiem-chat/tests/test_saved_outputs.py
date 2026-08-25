from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.main import create_app
from app.saved_outputs import (
    D1SavedOutputStore,
    MAX_OUTPUT_CONTENT_CHARS,
    SavedOutputRecord,
    validate_output_content,
    validate_output_id,
    validate_output_title,
)

SESSION_SECRET = "phase12-session-secret-not-a-real-credential-000000"
OWNER_ID = "usr_" + "a" * 32
OTHER_ID = "usr_" + "b" * 32
PROJECT_ID = "proj_" + "c" * 32
OTHER_PROJECT_ID = "proj_" + "d" * 32
CONVERSATION_ID = "chat_" + "e" * 32


def google_settings(**overrides):
    values = dict(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="phase12-client.apps.googleusercontent.com",
        google_client_secret="unit-test-google-secret",
        session_secret=SESSION_SECRET,
        session_max_age_seconds=3600,
    )
    values.update(overrides)
    return Settings.from_values(**values)


class MemoryHistory:
    def __init__(self):
        self.conversations = {}
        self.projects = {}

    async def get_conversation(self, user_id, conversation_id):
        row = self.conversations.get(conversation_id)
        if not row or row["user_id"] != user_id:
            return None
        return {
            "id": conversation_id,
            "project_id": row.get("project_id"),
            "messages": list(row.get("messages", [])),
        }

    async def get_project(self, user_id, project_id):
        row = self.projects.get(project_id)
        if not row or row["user_id"] != user_id:
            return None
        return row


class MemorySavedOutputStore:
    def __init__(self):
        self.rows = {}
        self.counter = 0
        self.create_calls = 0

    async def list_outputs(self, user_id, limit=100):
        rows = [row for row in self.rows.values() if row["user_id"] == user_id]
        rows.sort(key=lambda row: row["record"].updated_at, reverse=True)
        return [row["record"] for row in rows[:limit]]

    async def get_output(self, user_id, output_id):
        row = self.rows.get(output_id)
        return row["record"] if row and row["user_id"] == user_id else None

    async def create_output(self, user_id, title, content, conversation_id=None, project_id=None):
        self.create_calls += 1
        self.counter += 1
        oid = "out_" + f"{self.counter:032x}"
        stamp = f"2026-08-25T07:10:{self.counter:02d}Z"
        record = SavedOutputRecord(
            id=oid,
            title=validate_output_title(title),
            content_text=validate_output_content(content),
            conversation_id=conversation_id,
            project_id=project_id,
            created_at=stamp,
            updated_at=stamp,
        )
        self.rows[oid] = {"user_id": user_id, "record": record}
        return record

    async def update_output_title(self, user_id, output_id, title):
        current = await self.get_output(user_id, output_id)
        if current is None:
            return None
        updated = replace(current, title=validate_output_title(title), updated_at="2026-08-25T07:20:00Z")
        self.rows[output_id]["record"] = updated
        return updated

    async def delete_output(self, user_id, output_id):
        current = await self.get_output(user_id, output_id)
        if current is None:
            return False
        del self.rows[output_id]
        return True


@pytest.mark.parametrize(
    ("value", "ok"),
    [
        ("out_" + "a" * 32, True),
        ("out_" + "A" * 32, False),
        ("out_short", False),
        (123, False),
    ],
)
def test_output_id_is_strict_hex(value, ok):
    if ok:
        assert validate_output_id(value) == value
    else:
        with pytest.raises(ValueError):
            validate_output_id(value)


def test_output_title_and_content_are_bounded():
    assert validate_output_title("  제주   여행 일정  ") == "제주 여행 일정"
    assert validate_output_content("  답변 내용  ") == "답변 내용"
    with pytest.raises(ValueError):
        validate_output_title("")
    with pytest.raises(ValueError):
        validate_output_title("x" * 101)
    with pytest.raises(ValueError):
        validate_output_content("x" * (MAX_OUTPUT_CONTENT_CHARS + 1))
    with pytest.raises(ValueError):
        validate_output_content("bad\x00text")


@pytest.mark.asyncio
async def test_outputs_fail_closed_without_auth_or_store():
    app = create_app(Settings.from_values())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/outputs")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "saved_outputs_unavailable"

    history = MemoryHistory()
    configured = create_app(google_settings(), history_store=history)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=configured), base_url="https://chat.example.test") as client:
        client.cookies.set(SESSION_COOKIE, create_session_token(google_settings(), OWNER_ID), domain="chat.example.test", path="/")
        unavailable = await client.get("/api/outputs")
    assert unavailable.status_code == 503


@pytest.mark.asyncio
async def test_saved_output_crud_is_owner_scoped_and_list_hides_content():
    history = MemoryHistory()
    history.projects[PROJECT_ID] = {"id": PROJECT_ID, "user_id": OWNER_ID}
    history.conversations[CONVERSATION_ID] = {
        "id": CONVERSATION_ID,
        "user_id": OWNER_ID,
        "project_id": PROJECT_ID,
        "messages": [],
    }
    store = MemorySavedOutputStore()
    settings = google_settings()
    app = create_app(settings, history_store=history, saved_output_store=store)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test") as client:
        client.cookies.set(SESSION_COOKIE, create_session_token(settings, OWNER_ID), domain="chat.example.test", path="/")
        created = await client.post(
            "/api/outputs",
            json={
                "title": "제주 여행 일정",
                "content": "첫째 날은 제주시에 머뭅니다.",
                "conversation_id": CONVERSATION_ID,
            },
        )
        assert created.status_code == 201
        output_id = created.json()["output"]["id"]
        assert created.json()["output"]["project_id"] == PROJECT_ID

        listing = await client.get("/api/outputs")
        assert listing.status_code == 200
        assert listing.json()["outputs"][0]["id"] == output_id
        assert "content" not in listing.json()["outputs"][0]
        assert "첫째 날" not in json.dumps(listing.json(), ensure_ascii=False)

        detail = await client.get(f"/api/outputs/{output_id}")
        assert detail.status_code == 200
        assert detail.json()["output"]["content"] == "첫째 날은 제주시에 머뭅니다."

        renamed = await client.patch(f"/api/outputs/{output_id}", json={"title": "제주 가족여행"})
        assert renamed.status_code == 200
        assert renamed.json()["output"]["title"] == "제주 가족여행"

        client.cookies.set(SESSION_COOKIE, create_session_token(settings, OTHER_ID), domain="chat.example.test", path="/")
        assert (await client.get(f"/api/outputs/{output_id}")).status_code == 404
        assert (await client.patch(f"/api/outputs/{output_id}", json={"title": "침범"})).status_code == 404
        assert (await client.delete(f"/api/outputs/{output_id}")).status_code == 404

        client.cookies.set(SESSION_COOKIE, create_session_token(settings, OWNER_ID), domain="chat.example.test", path="/")
        deleted = await client.delete(f"/api/outputs/{output_id}")
        assert deleted.status_code == 200 and deleted.json()["deleted"] is True
        assert CONVERSATION_ID in history.conversations
        assert PROJECT_ID in history.projects


@pytest.mark.asyncio
async def test_provenance_ids_are_server_verified_before_save():
    history = MemoryHistory()
    history.projects[PROJECT_ID] = {"id": PROJECT_ID, "user_id": OWNER_ID}
    history.projects[OTHER_PROJECT_ID] = {"id": OTHER_PROJECT_ID, "user_id": OWNER_ID}
    history.conversations[CONVERSATION_ID] = {
        "id": CONVERSATION_ID,
        "user_id": OWNER_ID,
        "project_id": PROJECT_ID,
        "messages": [],
    }
    store = MemorySavedOutputStore()
    settings = google_settings()
    app = create_app(settings, history_store=history, saved_output_store=store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test") as client:
        client.cookies.set(SESSION_COOKIE, create_session_token(settings, OWNER_ID), domain="chat.example.test", path="/")
        mismatch = await client.post(
            "/api/outputs",
            json={
                "title": "잘못된 연결",
                "content": "내용",
                "conversation_id": CONVERSATION_ID,
                "project_id": OTHER_PROJECT_ID,
            },
        )
        missing = await client.post(
            "/api/outputs",
            json={
                "title": "없는 대화",
                "content": "내용",
                "conversation_id": "chat_" + "f" * 32,
            },
        )
    assert mismatch.status_code == 404
    assert missing.status_code == 404
    assert store.create_calls == 0


@pytest.mark.asyncio
async def test_saved_output_is_not_automatic_chat_context():
    secret = "SAVED-OUTPUT-SECRET-MUST-NOT-ENTER-MODEL-CONTEXT"
    store = MemorySavedOutputStore()
    await store.create_output(OWNER_ID, "private", secret)
    seen = {}

    async def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": "새 답변"}}],
            "business14": {
                "request_id": "b14req_outputs",
                "route_mode": "auto",
                "selected_model": "openrouter/free",
                "selected_provider": "OpenRouter",
            },
        })

    app = create_app(
        Settings(runtime_mode="b14", b14_base_url="https://b14.example"),
        transport=httpx.MockTransport(handler),
        saved_output_store=store,
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/chat", json={"messages": [{"role": "user", "content": "새 질문"}], "mode": "auto"})
    assert response.status_code == 200
    assert secret not in json.dumps(seen["body"], ensure_ascii=False)
    assert seen["body"]["messages"][-1] == {"role": "user", "content": "새 질문"}


@pytest.mark.asyncio
async def test_document_chat_does_not_create_saved_output_implicitly():
    store = MemorySavedOutputStore()
    app = create_app(Settings(runtime_mode="mock"), saved_output_store=store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/chat",
            json={
                "messages": [{"role": "user", "content": "이 문서를 요약해줘"}],
                "mode": "auto",
                "attachments": [{
                    "type": "document",
                    "name": "private.txt",
                    "media_type": "text/plain",
                    "text": "ATTACHMENT-CONTENT-IS-NOT-A-SAVED-OUTPUT",
                }],
            },
        )
    assert response.status_code == 200
    assert store.rows == {}


class FakeStatement:
    def __init__(self, db, sql):
        self.db = db
        self.sql = sql
        self.values = ()

    def bind(self, *values):
        self.values = values
        self.db.binds.append((self.sql, values))
        return self

    async def first(self):
        if "COUNT(*) AS output_count" in self.sql:
            return {"output_count": 0}
        return None

    async def run(self):
        return {"results": []}


class FakeDB:
    def __init__(self):
        self.sql = []
        self.binds = []

    def prepare(self, sql):
        self.sql.append(sql)
        return FakeStatement(self, sql)


@pytest.mark.asyncio
async def test_d1_saved_output_content_is_bound_not_interpolated_into_sql():
    db = FakeDB()
    store = D1SavedOutputStore(db)
    secret = "PRIVATE SAVED ANSWER CONTENT"
    created = await store.create_output(OWNER_ID, "제목", secret, CONVERSATION_ID, PROJECT_ID)
    assert created.content_text == secret
    sql_text = "\n".join(db.sql)
    assert secret not in sql_text
    assert OWNER_ID not in sql_text
    assert any(secret in values for _, values in db.binds)
    assert any(CONVERSATION_ID in values and PROJECT_ID in values for _, values in db.binds)


def test_saved_outputs_ui_is_additive_and_truthful():
    root = Path(__file__).resolve().parents[1]
    repo = root.parents[1]
    html = (root / "static/index.html").read_text(encoding="utf-8")
    js = (root / "static/outputs.js").read_text(encoding="utf-8")
    worker = (root / "worker.py").read_text(encoding="utf-8")

    assert '<link rel="stylesheet" href="./outputs.css" />' in html
    assert '<script src="./outputs.js"></script>' in html
    assert 'id="outputsNavButton"' in html and "hidden" in html
    assert "저장한 답변" in html
    assert 'id="savedOutputDialog"' in html
    assert 'fetch("/api/outputs"' in js
    assert "navigator.clipboard" in js and "document.execCommand" in js
    assert "new Blob([text]" in js and "URL.createObjectURL" in js and "URL.revokeObjectURL" in js
    assert 'save.hidden = !outputsReady' in js
    assert "window.confirm" in js
    assert "innerHTML" not in js
    assert "D1SavedOutputStore" in worker
    assert "create_app(settings=settings, history_store=history_store)" in worker

    assert (root / "static/styles.css").read_bytes() == (
        repo / "reference/business-62-padiem-chat-v1/styles.css"
    ).read_bytes()
    assert (root / "static/outputs.css").is_file()


def test_migration_is_plain_text_owner_scoped_storage_only():
    root = Path(__file__).resolve().parents[1]
    migration = (root / "migrations/004_saved_outputs.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS saved_outputs" in migration
    assert "content_text TEXT NOT NULL" in migration
    assert "REFERENCES users(id)" in migration
    assert "REFERENCES conversations(id) ON DELETE SET NULL" in migration
    assert "REFERENCES projects(id) ON DELETE SET NULL" in migration
    assert "BLOB" not in migration.upper()
    assert "base64" not in migration.lower()
