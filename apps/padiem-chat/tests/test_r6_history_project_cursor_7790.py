"""R6 첫 구역 회귀 — 프로젝트 커서가 `history.py` 재수출로 같은 결과를 낸다 (#7790).

소스 문자열이 아니라 실제 호출로 검증한다. 지역·모의만 사용한다(운영 DB·로그인·답변 생성 없음).
"""
from __future__ import annotations

import asyncio
import base64
import sqlite3

import pytest

from app import history as history_entry
from app import history_project_cursor as cursor_module
from app.history import (
    D1HistoryStore,
    PRODUCT_SCOPE_CHAT,
    ProjectCursorError,
    decode_project_cursor,
    encode_project_cursor,
)
from app.history_project_cursor import (
    PROJECT_CURSOR_MAX_CHARS as MODULE_MAX,
    ProjectCursorError as ModuleCursorError,
)


def test_reexport_names_are_the_same_objects() -> None:
    assert history_entry.ProjectCursorError is cursor_module.ProjectCursorError
    assert history_entry.encode_project_cursor is cursor_module.encode_project_cursor
    assert history_entry.decode_project_cursor is cursor_module.decode_project_cursor
    assert history_entry.PROJECT_CURSOR_MAX_CHARS is cursor_module.PROJECT_CURSOR_MAX_CHARS
    assert history_entry.PROJECT_CURSOR_MAX_CHARS == MODULE_MAX == 512


def test_direct_call_roundtrip_through_both_entries() -> None:
    from app.history import encode_project_cursor as via_entry
    cursor = via_entry("2026-11-02T00:00:00Z", "proj_" + "a" * 32)
    assert decode_project_cursor(cursor) == ("2026-11-02T00:00:00Z", "proj_" + "a" * 32)
    assert cursor_module.decode_project_cursor(cursor) == ("2026-11-02T00:00:00Z", "proj_" + "a" * 32)
    assert encode_project_cursor("2026-11-02T00:00:00Z", "proj_" + "a" * 32) == cursor


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
        None,
        123,
    ],
)
def test_invalid_cursor_still_raises_the_same_error(cursor) -> None:
    with pytest.raises(ModuleCursorError):
        decode_project_cursor(cursor)


from _support.b66_conversation_isolation import D1Sqlite, OWNER, setup_database


def _seed_projects(db, user_id: str, count: int) -> None:
    for index in range(count):
        db.execute(
            "INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?)",
            (
                "proj_%s_%03d" % (user_id[-1], index),
                user_id,
                "프로젝트 %03d" % index,
                "",
                "2026-11-01T00:00:00Z",
                "2026-11-01T%02d:%02d:00Z" % (index // 60, index % 60),
            ),
        )
    db.commit()


def test_list_projects_page_paging_unchanged() -> None:
    db = setup_database()
    store = D1HistoryStore(D1Sqlite(db))
    owner = OWNER
    _seed_projects(db, owner, 120)
    expected = [
        row[0]
        for row in db.execute(
            "SELECT id FROM projects WHERE user_id=? ORDER BY updated_at DESC, id DESC",
            (owner,),
        )
    ]
    seen: list[str] = []
    cursor = None
    pages = 0
    while True:
        page, cursor = asyncio.run(store.list_projects_page(owner, cursor=cursor))
        pages += 1
        seen.extend(item.id for item in page)
        if cursor is None:
            break
        assert pages < 5
    assert pages == 3
    assert seen == expected
    db.close()


def test_conversation_list_search_and_preview_unchanged() -> None:
    db = setup_database()
    store = D1HistoryStore(D1Sqlite(db))
    owner = OWNER
    self_cid = asyncio.run(
        store.append_exchange(
            owner, None, "파디엠 견적 요청", "합성 응답 본문", product_scope=PRODUCT_SCOPE_CHAT
        )
    )
    asyncio.run(
        store.append_exchange(
            owner, None, "다른 주제", "다른 응답", product_scope=PRODUCT_SCOPE_CHAT
        )
    )
    listed = asyncio.run(store.list_conversations(owner, product_scope=PRODUCT_SCOPE_CHAT))
    assert self_cid in {row["id"] for row in listed} and len(listed) == 2

    hits = asyncio.run(store.search_conversations(owner, "견적", product_scope=PRODUCT_SCOPE_CHAT))
    assert [hit["id"] for hit in hits] == [self_cid]

    detail = asyncio.run(store.get_conversation(owner, self_cid, product_scope=PRODUCT_SCOPE_CHAT))
    assert detail is not None
    assert detail["id"] == self_cid
    assert detail["messages"] == [
        {"role": "user", "content": "파디엠 견적 요청"},
        {"role": "assistant", "content": "합성 응답 본문"},
    ]
    db.close()
