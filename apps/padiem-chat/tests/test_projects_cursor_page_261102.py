"""#5882: the project list is paged, so the 51st project is reachable.

The old list was ``LIMIT 50`` with no cursor: creating a project never stopped,
but everything past the fiftieth simply did not appear. These tests pin the
whole page contract on the real SQLite-shaped store and on the route:

* 120 projects arrive over three pages, in the same order the first page used
  (most recently updated, ties broken by id descending), with no duplicates;
* the account condition rides the cursor query too, so another account's cursor
  cannot reveal whose row it pointed at;
* a cursor this store never issued is a 400 with one plain Korean sentence —
  the cursor text is not echoed and no internal name is shown;
* a caller that sends no cursor gets exactly the old first page (regression).
"""
from __future__ import annotations

import base64
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.datastructures import QueryParams

from app import project_routes
from app.history import (
    MAX_PROJECTS,
    D1HistoryStore,
    ProjectCursorError,
    decode_project_cursor,
    encode_project_cursor,
)

OWNER = "usr_" + "a" * 32
OTHER = "usr_" + "b" * 32


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
    """The smallest D1-shaped adapter: this store only ever prepares statements."""

    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.execute(
            "CREATE TABLE projects (id TEXT PRIMARY KEY, user_id TEXT, name TEXT, "
            "instructions TEXT, created_at TEXT, updated_at TEXT)"
        )

    def prepare(self, sql: str) -> _Statement:
        return _Statement(self.connection, sql)

    def seed(self, user_id: str, count: int, *, shared_stamp: int = 0) -> None:
        """Insert ``count`` projects, oldest first, ``shared_stamp`` of them tied."""
        for index in range(count):
            self.connection.execute(
                "INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?)",
                (
                    "proj_%s_%03d" % (user_id[-1], index),
                    user_id,
                    "프로젝트 %03d" % index,
                    "",
                    "2026-11-01T00:00:00Z",
                    # Every row gets a distinct stamp except the tied block, which
                    # all share one value so the id tie-break is exercised.
                    "2026-11-02T00:00:00Z" if index < shared_stamp
                    else "2026-11-01T%02d:%02d:00Z" % (index // 60, index % 60),
                ),
            )
        self.connection.commit()


def _store() -> tuple[_SqliteDb, D1HistoryStore]:
    db = _SqliteDb()
    return db, D1HistoryStore(db)


def _request(query: str, store) -> SimpleNamespace:
    return SimpleNamespace(
        method="GET",
        query_params=QueryParams(query),
        app=SimpleNamespace(state=SimpleNamespace(history_store=store)),
    )


def _body(response) -> dict:
    return json.loads(response.body)


@pytest.fixture(autouse=True)
def _authenticated(monkeypatch):
    monkeypatch.setattr(project_routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(project_routes, "current_user_id", lambda request: OWNER)


# ── cursor shape ────────────────────────────────────────────────────────────


def test_a_cursor_round_trips_the_sort_key():
    cursor = encode_project_cursor("2026-11-02T00:00:00Z", "proj_a_007")
    assert decode_project_cursor(cursor) == ("2026-11-02T00:00:00Z", "proj_a_007")


@pytest.mark.parametrize(
    "cursor",
    [
        "",
        "not-a-cursor",
        "!!!",
        base64.urlsafe_b64encode(b"[1,2,3]").decode().rstrip("="),
        base64.urlsafe_b64encode(b'{"u":"x"}').decode().rstrip("="),
        base64.urlsafe_b64encode(b'{"u":1,"i":2}').decode().rstrip("="),
        "A" * 513,
    ],
)
def test_a_cursor_this_store_did_not_issue_is_refused(cursor: str):
    with pytest.raises(ProjectCursorError):
        decode_project_cursor(cursor)


# ── real SQL: three pages, no duplicates, the same order ────────────────────


@pytest.mark.asyncio
async def test_120_projects_arrive_over_three_pages_in_order():
    db, store = _store()
    db.seed(OWNER, 120)
    expected = [
        row[0]
        for row in db.connection.execute(
            "SELECT id FROM projects WHERE user_id=? ORDER BY updated_at DESC, id DESC",
            (OWNER,),
        )
    ]

    seen: list[str] = []
    cursor = None
    pages = 0
    while True:
        page, cursor = await store.list_projects_page(OWNER, cursor=cursor)
        pages += 1
        assert len(page) <= MAX_PROJECTS
        seen.extend(item.id for item in page)
        if cursor is None:
            break
        assert pages < 5  # a cursor that never ends would loop here

    assert pages == 3
    assert len(seen) == 120
    assert len(set(seen)) == 120, "a project appeared twice across pages"
    assert seen == expected


@pytest.mark.asyncio
async def test_rows_with_the_same_updated_at_keep_a_stable_tie_break():
    db, store = _store()
    db.seed(OWNER, 70, shared_stamp=40)
    expected = [
        row[0]
        for row in db.connection.execute(
            "SELECT id FROM projects WHERE user_id=? ORDER BY updated_at DESC, id DESC",
            (OWNER,),
        )
    ]

    first, cursor = await store.list_projects_page(OWNER)
    second, cursor2 = await store.list_projects_page(OWNER, cursor=cursor)
    assert cursor is not None and cursor2 is None
    assert [item.id for item in first + second] == expected
    # The tied block starts with the highest id and reads downwards.
    tied = [row for row in expected if row.startswith("proj_a_0")][:40]
    assert tied == sorted(tied, reverse=True)


@pytest.mark.asyncio
async def test_the_first_page_without_a_cursor_is_the_old_list():
    db, store = _store()
    db.seed(OWNER, 120)
    assert [item.id for item in await store.list_projects(OWNER)] == [
        item.id for item in (await store.list_projects_page(OWNER))[0]
    ]


# ── route ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_route_returns_a_next_cursor_and_the_second_page():
    db, store = _store()
    db.seed(OWNER, 120)

    first = await project_routes.projects_collection(_request("", store))
    body = _body(first)
    assert first.status_code == 200
    assert len(body["projects"]) == MAX_PROJECTS
    assert isinstance(body["next_cursor"], str) and body["next_cursor"]

    second = await project_routes.projects_collection(
        _request("cursor=" + body["next_cursor"], store)
    )
    assert second.status_code == 200
    second_body = _body(second)
    ids = {item["id"] for item in body["projects"]}
    assert not ids & {item["id"] for item in second_body["projects"]}
    assert len(second_body["projects"]) == MAX_PROJECTS


@pytest.mark.asyncio
async def test_a_forged_cursor_is_a_plain_korean_400():
    db, store = _store()
    db.seed(OWNER, 120)
    # Structurally invalid: base64 of a JSON body with the wrong shape.
    forged = base64.urlsafe_b64encode(b'{"u": 1}').decode().rstrip("=")

    response = await project_routes.projects_collection(_request("cursor=" + forged, store))
    body = _body(response)

    assert response.status_code == 400
    assert body["error"]["code"] == "invalid_cursor"
    message = body["error"]["message"]
    assert "처음부터 다시" in message
    for leaked in ("proj_b_000", "invalid project cursor", "ProjectCursorError", "Traceback"):
        assert leaked not in message


@pytest.mark.asyncio
async def test_another_accounts_cursor_only_ever_pages_this_account():
    db, store = _store()
    db.seed(OWNER, 60)
    db.seed(OTHER, 60)
    first_page, _ = await store.list_projects_page(OWNER)
    assert len(first_page) == MAX_PROJECTS
    cursor_at = encode_project_cursor(first_page[-1].updated_at, first_page[-1].id)

    page, next_cursor = await store.list_projects_page(OTHER, cursor=cursor_at)
    assert page, "the other account still gets its own older rows"
    assert all(item.id.startswith("proj_b_") for item in page)
    assert not any(item.id.startswith("proj_a_") for item in page)
    # The cursor is a position, not a pointer into someone's rows: the same
    # position applied to this account returns only this account's older rows.
    expected = [
        row[0]
        for row in db.connection.execute(
            "SELECT id FROM projects WHERE user_id=? "
            "AND (updated_at < ? OR (updated_at = ? AND id < ?)) "
            "ORDER BY updated_at DESC, id DESC",
            (OTHER, first_page[-1].updated_at, first_page[-1].updated_at, first_page[-1].id),
        )
    ]
    assert [item.id for item in page] == expected[:MAX_PROJECTS]
    assert next_cursor is None


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["limit=0", "limit=abc", "limit=-3"])
async def test_a_bad_limit_is_400(query: str):
    db, store = _store()
    db.seed(OWNER, 10)
    response = await project_routes.projects_collection(_request(query, store))
    assert response.status_code == 400
    assert _body(response)["error"]["code"] == "invalid_limit"


@pytest.mark.asyncio
async def test_a_store_without_paging_still_answers_the_first_page():
    class _LegacyStore:
        async def list_projects(self, user_id):
            return []

    response = await project_routes.projects_collection(_request("", _LegacyStore()))
    assert response.status_code == 200
    assert _body(response) == {"projects": [], "next_cursor": None}


def test_the_screen_offers_one_more_page_at_a_time():
    """The list keeps its shape and grows only on demand: 44px, 14px copy."""
    static = Path(project_routes.__file__).resolve().parents[1] / "static"
    script = (static / "app.js").read_text(encoding="utf-8")
    assert "projectsMore" in script
    assert "loadMoreProjects" in script
    assert "cursor=${encodeURIComponent(cursor)}" in script
    locale = (static / "locale.js").read_text(encoding="utf-8")
    assert locale.count('"projects-more":') == 2  # ko + en
    css = (static / "padiem-foundation.css").read_text(encoding="utf-8")
    # #5882 follow-up: the same "더 보기" rule now sizes the project, saved-answer
    # and memory buttons, so the selector lists all three (and none loses 44px).
    selector = ":is(.project-more, .output-more, .memory-more) {"
    assert selector in css
    assert "min-height: 44px" in css.split(selector, 1)[1][:200]
    for button in (".output-more", ".memory-more"):
        assert button in selector
