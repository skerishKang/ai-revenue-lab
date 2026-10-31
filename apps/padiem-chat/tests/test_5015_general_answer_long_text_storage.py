"""#5015 ? a long model-only answer must survive the real storage path.

The model-only answer is stored under a run-scoped message id, and an answer
longer than ``MAX_HISTORY_MESSAGE_CHARS`` becomes a truncated D1 preview plus a
private R2 original. The private key validator accepts only the canonical
message identities, so a run-scoped id that does not follow that convention is
rejected *before* the D1 rows land, and the whole conversation save fails.

These tests drive the real ``D1HistoryStore.append_exchange`` over a SQLite
database behind the D1 interface, so the schema constraints and the R2 key
validation are the authority being measured, not a double of the store.

The recovery read is measured the same way: the answer the run actually
produced has to come back through the real recovery API, not through the
private original reader. A bounded D1 preview is never the answer.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from starlette.requests import Request

from app.history import (
    GENERAL_ANSWER_MESSAGE_SALT,
    HISTORY_PREVIEW_SUFFIX,
    MAX_HISTORY_MESSAGE_CHARS,
    PRODUCT_SCOPE_CHAT,
    D1HistoryStore,
    HistoryError,
    general_answer_message_id,
)
from app.claw_routes import claw_pending_result

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
MIGRATION_NAMES = (
    "001_auth_history.sql",
    "002_projects.sql",
    "003_project_files.sql",
    "009_claw_run_history.sql",
    "014_claw_run_history_conversation.sql",
    "015_claw_run_history_workspace.sql",
    "020_claw_local_task_correlation.sql",
    "042_conversation_product_scope.sql",
    "047_oracle_mesh_dispatch.sql",
)

OWNER = "usr_" + "a" * 32
CONVERSATION = "chat_" + "c" * 32
# The recovery route resolves a run id by its own canonical grammar, so the id
# is the canonical one the general lane mints.
RUN_ID = "run_" + "5" * 24
USER_TEXT = "폴더에서 읽은 원문을 요약해줘"
ASSISTANT_TEXT = "LONG-ANSWER-ORIGINAL-" + ("가" * 9000)


class _SqliteD1Statement:
    def __init__(self, db: "_SqliteD1", sql: str, values: tuple = ()) -> None:
        self._db = db
        self._sql = sql
        self._values = values

    def bind(self, *values: Any) -> "_SqliteD1Statement":
        return _SqliteD1Statement(self._db, self._sql, values)

    async def run(self) -> dict[str, Any]:
        return await self._db.execute(self._sql, self._values)

    async def first(self) -> dict[str, Any] | None:
        result = await self._db.execute(self._sql, self._values)
        rows = result["results"]
        return rows[0] if rows else None

    async def all(self) -> list[dict[str, Any]]:
        result = await self._db.execute(self._sql, self._values)
        return list(result["results"])


class _SqliteD1:
    """Cloudflare D1 interface over one SQLite connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def prepare(self, sql: str) -> _SqliteD1Statement:
        return _SqliteD1Statement(self, sql)

    async def batch(self, statements: list[_SqliteD1Statement]) -> list[Any]:
        results: list[Any] = []
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            for statement in statements:
                cursor = self.conn.execute(statement._sql, statement._values)
                columns = [item[0] for item in cursor.description] if cursor.description else []
                rows = cursor.fetchall() if columns else []
                if columns:
                    results.append({"results": [dict(zip(columns, row)) for row in rows]})
                else:
                    written = cursor.rowcount if cursor.rowcount >= 0 else 0
                    results.append({"meta": {"rows_written": written}})
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        return results

    async def execute(self, sql: str, values: tuple) -> dict[str, Any]:
        cursor = self.conn.execute(sql, values)
        rows = [dict(row) for row in cursor.fetchall()]
        return {"results": rows, "success": True, "meta": {"changes": cursor.rowcount}}


class _PrivateR2:
    """Private full-context bucket double; keys are server-derived only."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.deleted: list[str] = []
        self.put_keys: list[str] = []

    async def put(self, key: str, payload: bytes, **_kwargs: Any) -> None:
        self.put_keys.append(key)
        self.objects[key] = bytes(payload)

    async def get(self, key: str) -> Any:
        data = self.objects.get(key)
        if data is None:
            return None
        return SimpleNamespace(size=len(data), arrayBuffer=lambda: data)

    async def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.objects.pop(key, None)


def _database() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    for name in MIGRATION_NAMES:
        conn.executescript((MIGRATIONS / name).read_text(encoding="utf-8"))
    conn.execute(
        "INSERT INTO users (id, auth_provider, provider_subject, email, display_name, picture_url, created_at, updated_at) "
        "VALUES (?, 'google', ?, ?, '', '', '2026-10-20T00:00:00.000Z', '2026-10-20T00:00:00.000Z')",
        (OWNER, "subject-owner", "owner@example.test"),
    )
    conn.execute(
        "INSERT INTO conversations (id, user_id, project_id, title, created_at, updated_at, product_scope) "
        "VALUES (?, ?, NULL, ?, ?, ?, ?)",
        (CONVERSATION, OWNER, "seeded", "t0", "t0", PRODUCT_SCOPE_CHAT),
    )
    return conn


def _store(conn: sqlite3.Connection) -> tuple[D1HistoryStore, _PrivateR2]:
    bucket = _PrivateR2()
    return D1HistoryStore(_SqliteD1(conn), full_context_bucket=bucket), bucket


def _rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in conn.execute(
            "SELECT id, role, content FROM messages WHERE conversation_id=? "
            "ORDER BY sequence_number ASC",
            (CONVERSATION,),
        )
    ]


def test_the_run_scoped_id_follows_the_canonical_message_identity() -> None:
    message_id = general_answer_message_id(RUN_ID)
    # Same deterministic shape the existing result-id convention produces.
    assert message_id.startswith("msg_ltr_")
    assert len(message_id) == len("msg_ltr_") + 40
    assert message_id == general_answer_message_id(RUN_ID)
    assert message_id != general_answer_message_id(RUN_ID + "-other")
    assert GENERAL_ANSWER_MESSAGE_SALT in GENERAL_ANSWER_MESSAGE_SALT


@pytest.mark.asyncio
async def test_a_long_run_scoped_answer_is_saved_and_its_original_recovers() -> None:
    conn = _database()
    store, bucket = _store(conn)
    message_id = general_answer_message_id(RUN_ID)

    conversation_id = await store.append_exchange(
        OWNER,
        CONVERSATION,
        USER_TEXT,
        ASSISTANT_TEXT,
        product_scope=PRODUCT_SCOPE_CHAT,
        assistant_message_id=message_id,
    )

    assert conversation_id == CONVERSATION
    rows = _rows(conn)
    assert [row["role"] for row in rows] == ["user", "assistant"]
    assistant = rows[1]
    assert assistant["id"] == message_id
    # A long answer is stored as a bounded preview, never silently truncated.
    assert len(assistant["content"]) == MAX_HISTORY_MESSAGE_CHARS
    assert str(assistant["content"]).endswith(HISTORY_PREVIEW_SUFFIX)

    key = f"claw-model-context/v1/{CONVERSATION}/{message_id}.utf8"
    assert bucket.put_keys == [key]
    assert bucket.deleted == []

    recovered = await store._read_full_message(
        CONVERSATION, {"id": message_id, "content": assistant["content"]}
    )
    assert recovered == ASSISTANT_TEXT


@pytest.mark.asyncio
async def test_an_invalid_run_scoped_id_still_fails_before_any_row_lands() -> None:
    conn = _database()
    store, bucket = _store(conn)

    with pytest.raises(HistoryError):
        await store.append_exchange(
            OWNER,
            CONVERSATION,
            USER_TEXT,
            ASSISTANT_TEXT,
            product_scope=PRODUCT_SCOPE_CHAT,
            assistant_message_id="run_5015_long_answer_general_answer",
        )

    assert _rows(conn) == []
    assert bucket.put_keys == []
    assert bucket.deleted == []


async def _completed_general_run(store: D1HistoryStore) -> None:
    """The real general-lane persistence of one model-only run."""
    await store.append_exchange(
        OWNER,
        CONVERSATION,
        USER_TEXT,
        ASSISTANT_TEXT,
        product_scope=PRODUCT_SCOPE_CHAT,
        assistant_message_id=general_answer_message_id(RUN_ID),
    )
    await store.record_claw_run(
        user_id=OWNER, run_id=RUN_ID, channel="web", action="general",
        title="Claw: " + USER_TEXT, status="completed",
        result_summary=ASSISTANT_TEXT[:200],
        conversation_id=CONVERSATION,
    )


def _recovery_request(store: D1HistoryStore) -> Request:
    request = Request({
        "type": "http", "method": "GET",
        "path": f"/api/claw/runs/{RUN_ID}/pending-result",
        "path_params": {"run_id": RUN_ID}, "headers": [],
    })
    request.scope["app"] = SimpleNamespace(
        state=SimpleNamespace(history_store=store)
    )
    return request


@pytest.mark.asyncio
async def test_the_recovery_api_returns_the_whole_stored_model_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The run's actual model answer, read through the real recovery API."""
    import app.claw_routes as routes

    conn = _database()
    store, _bucket = _store(conn)
    await _completed_general_run(store)

    monkeypatch.setattr(routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(routes, "current_user_id", lambda request: OWNER)
    response = await claw_pending_result(_recovery_request(store))

    assert response.status_code == 200
    body = json.loads(response.body)["result"]
    assert body["answer"] == ASSISTANT_TEXT
    assert body["answer_source"] == "model_reply"
    # The bounded D1 preview is never the answer.
    assert len(body["answer"]) > MAX_HISTORY_MESSAGE_CHARS
    assert not body["answer"].endswith(HISTORY_PREVIEW_SUFFIX)


@pytest.mark.asyncio
async def test_a_model_reply_without_its_stored_original_stays_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing original stays unavailable; the preview is not the answer."""
    import app.claw_routes as routes

    conn = _database()
    store, bucket = _store(conn)
    await _completed_general_run(store)
    # The private original is gone: only the bounded preview is left in D1.
    bucket.objects.clear()

    monkeypatch.setattr(routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(routes, "current_user_id", lambda request: OWNER)
    response = await claw_pending_result(_recovery_request(store))

    assert response.status_code == 503
    assert json.loads(response.body)["error"]["code"] == "run_result_unavailable"


@pytest.mark.asyncio
async def test_a_duplicate_completion_event_keeps_one_answer_and_its_original() -> None:
    """The deterministic run-scoped id makes a repeated completion safe."""
    conn = _database()
    store, bucket = _store(conn)
    await _completed_general_run(store)
    key = f"claw-model-context/v1/{CONVERSATION}/{general_answer_message_id(RUN_ID)}.utf8"

    # The same completion event again: the run-scoped message id is the same,
    # so the second record is refused instead of duplicating the answer.
    with pytest.raises(sqlite3.IntegrityError):
        await store.append_exchange(
            OWNER,
            CONVERSATION,
            USER_TEXT,
            ASSISTANT_TEXT,
            product_scope=PRODUCT_SCOPE_CHAT,
            assistant_message_id=general_answer_message_id(RUN_ID),
        )

    rows = _rows(conn)
    assert len(rows) == 2
    assert [row["role"] for row in rows] == ["user", "assistant"]
    # The stored original of the first record is still recoverable.
    assert bucket.deleted == []
    assert bucket.objects[key] == ASSISTANT_TEXT.encode("utf-8")
    resolved = await store.get_claw_run_result(OWNER, RUN_ID, CONVERSATION)
    assert resolved == {"answer": ASSISTANT_TEXT, "answer_source": "model_reply"}
