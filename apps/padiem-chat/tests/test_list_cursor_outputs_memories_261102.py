"""#5882: saved answers and approved memories are paged, not truncated.

Both lists used to stop at a fixed row count with no way to see the rest
(``MAX_OUTPUT_LIST`` 100, ``MAX_APPROVED_MEMORIES`` 30). These tests pin the same
page contract the project list already uses:

* the whole list arrives over pages, in the list's own order (newest first, id
  descending breaks the tie), with no row repeated and no row skipped;
* the account (and workspace) condition rides the cursor query too;
* a cursor this store never issued is a 400 with one plain Korean sentence, and
  the cursor text is not echoed;
* a caller that sends no cursor gets exactly the old first page.
"""
from __future__ import annotations

import base64
import json
import sqlite3
from types import SimpleNamespace

import pytest
from starlette.datastructures import QueryParams

from app import claw_memory_routes, saved_output_routes
from app.approved_memory import MAX_APPROVED_MEMORIES, D1ApprovedMemoryStore
from app.saved_outputs import MAX_OUTPUT_LIST, D1SavedOutputStore

OWNER = "usr_" + "a" * 32
OTHER = "usr_" + "b" * 32
WORKSPACE = "ws_" + "c" * 32
OTHER_WORKSPACE = "ws_" + "d" * 32


class _Statement:
    def __init__(self, connection: sqlite3.Connection, sql: str) -> None:
        self._connection = connection
        self._sql = sql
        self._params: list[object] = []

    def bind(self, *params: object) -> "_Statement":
        self._params = list(params)
        return self

    async def run(self) -> SimpleNamespace:
        cursor = self._connection.execute(self._sql, self._params)
        columns = [column[0] for column in cursor.description] if cursor.description else []
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        self._connection.commit()
        return SimpleNamespace(results=rows)


class _SqliteDb:
    """The smallest D1-shaped adapter these two stores ever need."""

    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.execute(
            "CREATE TABLE saved_outputs (id TEXT PRIMARY KEY, user_id TEXT, title TEXT, "
            "content_text TEXT, conversation_id TEXT, project_id TEXT, "
            "created_at TEXT, updated_at TEXT)"
        )
        self.connection.execute(
            "CREATE TABLE claw_approved_memory (id TEXT PRIMARY KEY, user_id TEXT, "
            "workspace_id TEXT, memory_type TEXT, name TEXT, note TEXT, "
            "source_channel TEXT, status TEXT, created_at TEXT, updated_at TEXT)"
        )

    def prepare(self, sql: str) -> _Statement:
        return _Statement(self.connection, sql)

    def seed_outputs(self, user_id: str, count: int, *, tied: int = 0) -> None:
        for index in range(count):
            stamp = ("2026-11-02T00:00:00Z" if index < tied
                     else "2026-11-01T%02d:%02d:00Z" % (index // 60, index % 60))
            self.connection.execute(
                "INSERT INTO saved_outputs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("out_%s_%03d" % (user_id[-1], index), user_id, "답변 %03d" % index,
                 "본문", None, None, "2026-10-31T00:00:00Z", stamp),
            )
        self.connection.commit()

    def seed_memories(self, user_id: str, workspace_id: str, count: int, *, tied: int = 0) -> None:
        for index in range(count):
            stamp = ("2026-11-02T00:00:00Z" if index < tied
                     else "2026-11-01T%02d:%02d:00Z" % (index // 60, index % 60))
            self.connection.execute(
                "INSERT INTO claw_approved_memory VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("mem_%s_%s_%03d" % (user_id[-1], workspace_id[-2:], index), user_id, workspace_id, "place",
                 "기억 %03d" % index, "메모", "kakao", "approved",
                 stamp, "2026-11-02T00:00:00Z"),
            )
        self.connection.commit()


# ── saved answers ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_220_saved_answers_arrive_over_three_pages_in_order():
    db = _SqliteDb()
    db.seed_outputs(OWNER, 220)
    store = D1SavedOutputStore(db)
    expected = [
        row[0]
        for row in db.connection.execute(
            "SELECT id FROM saved_outputs WHERE user_id=? ORDER BY updated_at DESC, id DESC",
            (OWNER,),
        )
    ]

    seen: list[str] = []
    cursor = None
    pages = 0
    while True:
        page, cursor = await store.list_outputs_page(OWNER, cursor=cursor)
        pages += 1
        assert len(page) <= MAX_OUTPUT_LIST
        seen.extend(item.id for item in page)
        if cursor is None:
            break
        assert pages < 6

    assert pages == 3
    assert len(seen) == 220 and len(set(seen)) == 220
    assert seen == expected


@pytest.mark.asyncio
async def test_saved_answers_with_the_same_stamp_keep_a_stable_order():
    db = _SqliteDb()
    db.seed_outputs(OWNER, 130, tied=40)
    store = D1SavedOutputStore(db)
    expected = [
        row[0]
        for row in db.connection.execute(
            "SELECT id FROM saved_outputs WHERE user_id=? ORDER BY updated_at DESC, id DESC",
            (OWNER,),
        )
    ]
    first, cursor = await store.list_outputs_page(OWNER)
    second, cursor2 = await store.list_outputs_page(OWNER, cursor=cursor)
    assert cursor is not None and cursor2 is None
    assert [item.id for item in first + second] == expected


@pytest.mark.asyncio
async def test_the_old_first_page_of_saved_answers_is_unchanged():
    db = _SqliteDb()
    db.seed_outputs(OWNER, 220)
    store = D1SavedOutputStore(db)
    assert [item.id for item in await store.list_outputs(OWNER)] == [
        item.id for item in (await store.list_outputs_page(OWNER))[0]
    ]


# ── approved memories ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_70_approved_memories_arrive_over_three_pages_in_order():
    db = _SqliteDb()
    db.seed_memories(OWNER, WORKSPACE, 70)
    store = D1ApprovedMemoryStore(db)
    expected = [
        row[0]
        for row in db.connection.execute(
            "SELECT id FROM claw_approved_memory WHERE user_id=? AND workspace_id=? "
            "ORDER BY created_at DESC, id DESC",
            (OWNER, WORKSPACE),
        )
    ]

    seen: list[str] = []
    cursor = None
    pages = 0
    while True:
        page, cursor = await store.list_approved_memories_page(
            user_id=OWNER, workspace_id=WORKSPACE, cursor=cursor,
        )
        pages += 1
        seen.extend(item["memory_id"] for item in page)
        if cursor is None:
            break
        assert pages < 6

    assert pages == 3
    assert len(seen) == 70 and len(set(seen)) == 70
    assert seen == expected


@pytest.mark.asyncio
async def test_memories_with_the_same_stamp_keep_a_stable_order():
    db = _SqliteDb()
    db.seed_memories(OWNER, WORKSPACE, 40, tied=20)
    store = D1ApprovedMemoryStore(db)
    expected = [
        row[0]
        for row in db.connection.execute(
            "SELECT id FROM claw_approved_memory WHERE user_id=? AND workspace_id=? "
            "ORDER BY created_at DESC, id DESC",
            (OWNER, WORKSPACE),
        )
    ]
    first, cursor = await store.list_approved_memories_page(
        user_id=OWNER, workspace_id=WORKSPACE,
    )
    second, cursor2 = await store.list_approved_memories_page(
        user_id=OWNER, workspace_id=WORKSPACE, cursor=cursor,
    )
    assert cursor is not None and cursor2 is None
    assert [item["memory_id"] for item in first + second] == expected


@pytest.mark.asyncio
async def test_the_old_first_page_of_memories_is_unchanged():
    db = _SqliteDb()
    db.seed_memories(OWNER, WORKSPACE, 70)
    store = D1ApprovedMemoryStore(db)
    assert [item["memory_id"] for item in await store.list_approved_memories(
        user_id=OWNER, workspace_id=WORKSPACE,
    )] == [item["memory_id"] for item in (await store.list_approved_memories_page(
        user_id=OWNER, workspace_id=WORKSPACE,
    ))[0]]


# ── routes ──────────────────────────────────────────────────────────────────


def _request(query: str, **state) -> SimpleNamespace:
    return SimpleNamespace(
        method="GET",
        query_params=QueryParams(query),
        app=SimpleNamespace(state=SimpleNamespace(**state)),
    )


def _body(response) -> dict:
    return json.loads(response.body)


@pytest.fixture(autouse=True)
def _authenticated(monkeypatch):
    monkeypatch.setattr(saved_output_routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(saved_output_routes, "current_user_id", lambda request: OWNER)
    monkeypatch.setattr(claw_memory_routes, "_require_owner", lambda request: OWNER)
    monkeypatch.setattr(claw_memory_routes, "_approved_store", lambda request: _STORE["value"])

    async def workspace(request, uid):
        return WORKSPACE

    monkeypatch.setattr(claw_memory_routes, "_resolve_memory_workspace", workspace)


_STORE: dict = {"value": None}


@pytest.mark.asyncio
async def test_the_outputs_route_returns_a_next_cursor_and_the_second_page():
    db = _SqliteDb()
    db.seed_outputs(OWNER, 220)
    store = D1SavedOutputStore(db)
    state = dict(history_store=SimpleNamespace(), saved_output_store=store)

    first = await saved_output_routes.outputs_collection(_request("", **state))
    body = _body(first)
    assert first.status_code == 200
    assert len(body["outputs"]) == MAX_OUTPUT_LIST
    assert isinstance(body["next_cursor"], str) and body["next_cursor"]

    second = await saved_output_routes.outputs_collection(
        _request("cursor=" + body["next_cursor"], **state)
    )
    assert second.status_code == 200
    assert not {item["id"] for item in body["outputs"]} & {
        item["id"] for item in _body(second)["outputs"]
    }


@pytest.mark.asyncio
async def test_the_memories_route_returns_a_next_cursor_and_the_second_page():
    db = _SqliteDb()
    db.seed_memories(OWNER, WORKSPACE, 70)
    store = D1ApprovedMemoryStore(db)
    _STORE["value"] = store

    first = await claw_memory_routes.claw_memory_list(_request(""))
    body = _body(first)
    assert first.status_code == 200
    assert len(body["memories"]) == MAX_APPROVED_MEMORIES
    assert isinstance(body["next_cursor"], str) and body["next_cursor"]

    second = await claw_memory_routes.claw_memory_list(
        _request("cursor=" + body["next_cursor"])
    )
    assert second.status_code == 200
    assert not {item["memory_id"] for item in body["memories"]} & {
        item["memory_id"] for item in _body(second)["memories"]
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["outputs", "memories"])
async def test_a_forged_cursor_is_a_plain_korean_400(route: str):
    db = _SqliteDb()
    db.seed_outputs(OWNER, 120)
    db.seed_memories(OWNER, WORKSPACE, 70)
    forged = base64.urlsafe_b64encode(b'{"u": 1}').decode().rstrip("=")

    if route == "outputs":
        state = dict(history_store=SimpleNamespace(), saved_output_store=D1SavedOutputStore(db))
        response = await saved_output_routes.outputs_collection(
            _request("cursor=" + forged, **state)
        )
    else:
        _STORE["value"] = D1ApprovedMemoryStore(db)
        response = await claw_memory_routes.claw_memory_list(_request("cursor=" + forged))

    body = _body(response)
    assert response.status_code == 400
    payload = body.get("error") or body
    assert payload["code"] == "invalid_cursor"
    assert "처음부터 다시" in payload["message"]
    for leaked in ("invalid project cursor", "ProjectCursorError", "Traceback"):
        assert leaked not in payload["message"]


@pytest.mark.asyncio
async def test_another_account_only_ever_pages_its_own_rows():
    db = _SqliteDb()
    db.seed_outputs(OWNER, 150)
    db.seed_outputs(OTHER, 150)
    store = D1SavedOutputStore(db)
    first_page, _ = await store.list_outputs_page(OWNER)
    from app.history import encode_project_cursor

    cursor_at = encode_project_cursor(first_page[-1].updated_at, first_page[-1].id)
    page, _ = await store.list_outputs_page(OTHER, cursor=cursor_at)
    assert page
    assert all(item.id.startswith("out_b_") for item in page)

    db2 = _SqliteDb()
    db2.seed_memories(OWNER, WORKSPACE, 70)
    db2.seed_memories(OWNER, OTHER_WORKSPACE, 70)
    memories = D1ApprovedMemoryStore(db2)
    own_first, _ = await memories.list_approved_memories_page(
        user_id=OWNER, workspace_id=WORKSPACE,
    )
    cursor_at = encode_project_cursor(own_first[-1]["created_at"], own_first[-1]["memory_id"])
    page, _ = await memories.list_approved_memories_page(
        user_id=OWNER, workspace_id=OTHER_WORKSPACE, cursor=cursor_at,
    )
    assert all(item["workspace_id"] == OTHER_WORKSPACE for item in page)


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["limit=0", "limit=abc", "limit=-1"])
async def test_a_bad_limit_is_400(query: str):
    db = _SqliteDb()
    db.seed_outputs(OWNER, 5)
    state = dict(history_store=SimpleNamespace(), saved_output_store=D1SavedOutputStore(db))
    outputs_response = await saved_output_routes.outputs_collection(_request(query, **state))
    assert outputs_response.status_code == 400
    assert _body(outputs_response)["error"]["code"] == "invalid_limit"

    _STORE["value"] = D1ApprovedMemoryStore(_SqliteDb())
    memory_response = await claw_memory_routes.claw_memory_list(_request(query))
    assert memory_response.status_code == 400


@pytest.mark.asyncio
async def test_stores_without_paging_still_answer_the_first_page():
    class _LegacyOutputs:
        async def list_outputs(self, user_id):
            return []

    response = await saved_output_routes.outputs_collection(
        _request("", history_store=SimpleNamespace(), saved_output_store=_LegacyOutputs())
    )
    assert response.status_code == 200
    assert _body(response) == {"outputs": [], "next_cursor": None}
