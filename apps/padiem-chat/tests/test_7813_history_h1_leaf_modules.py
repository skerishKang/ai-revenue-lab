"""T3 H1 회귀 — 예외·프로필·협약·레인 보조가 `history.py` 재수출로 같은 결과를 낸다 (#7813).

소스 문자열이 아니라 실제 호출로 검증한다. 지역·모의만 사용한다(운영 DB·로그인·답변 생성 없음).
"""
from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timezone

import pytest

from app import history as history_entry
from app import history_errors as errors_module
from app import history_text as text_module
from app import history_types as types_module

from test_b66_conversation_isolation_4657 import D1Sqlite, OWNER, setup_database


def test_reexport_names_are_the_same_objects() -> None:
    for name in (
        "HistoryError",
        "HistoryContextIncomplete",
        "HistoryForbidden",
        "HistoryConflict",
        "HistoryPinUnavailable",
    ):
        assert getattr(history_entry, name) is getattr(errors_module, name), name
    for name in (
        "UserProfile",
        "PasswordCredential",
        "ProjectProfile",
        "HistoryStore",
        "VerifiedDispatch",
        "_VERIFIED_FOR",
        "MAX_RECENT_CONVERSATIONS",
        "MAX_PROJECTS",
        "MAX_CLAW_RUNS",
    ):
        assert getattr(history_entry, name) is getattr(types_module, name), name
    for name in ("_lane_seconds", "_lane_count_age", "_lane_node"):
        assert getattr(history_entry, name) is getattr(text_module, name), name


def test_exception_hierarchy_direct_call() -> None:
    assert issubclass(history_entry.HistoryError, RuntimeError)
    for name in (
        "HistoryContextIncomplete",
        "HistoryForbidden",
        "HistoryConflict",
        "HistoryPinUnavailable",
    ):
        assert issubclass(getattr(history_entry, name), history_entry.HistoryError)
    with pytest.raises(history_entry.HistoryForbidden, match="scope"):
        raise history_entry.HistoryForbidden("scope is not recognized")


def test_profiles_public_dict_direct_call() -> None:
    user = history_entry.UserProfile("usr_1", "a@example.test", "이름", "https://pic")
    assert user.public_dict() == {"email": "a@example.test", "name": "이름", "picture": "https://pic"}
    assert types_module.UserProfile("usr_1", "a@example.test", "이름", "https://pic") == user
    project = history_entry.ProjectProfile("proj_1", "제목", "지시", "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
    assert project.public_dict() == {
        "id": "proj_1",
        "name": "제목",
        "instructions": "지시",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z",
    }
    credential = history_entry.PasswordCredential(user, "name", "hash", 0, None)
    assert credential.user is user and credential.created_at is None


def test_history_store_protocol_defaults_unchanged() -> None:
    assert inspect.signature(history_entry.HistoryStore.list_conversations).parameters["limit"].default == 30
    assert inspect.signature(history_entry.HistoryStore.search_conversations).parameters["limit"].default == 20
    assert inspect.signature(history_entry.HistoryStore.list_projects_page).parameters["limit"].default == 50
    assert inspect.signature(history_entry.HistoryStore.list_recent_claw_runs).parameters["limit"].default == 30
    assert history_entry.MAX_RECENT_CONVERSATIONS == 30
    assert history_entry.MAX_PROJECTS == 50
    assert history_entry.MAX_CLAW_RUNS == 30


def test_verified_dispatch_direct_call() -> None:
    marked = history_entry.VerifiedDispatch({"dispatch_id": "d1"})
    marked[history_entry._VERIFIED_FOR] = "usr_owner"
    assert isinstance(marked, dict)
    assert marked.verified_for == "usr_owner"
    assert history_entry.VerifiedDispatch({"a": 1}).verified_for == ""
    assert types_module.VerifiedDispatch({"a": 1}).verified_for == ""


MOMENT = datetime(2026, 1, 1, 0, 1, 0, tzinfo=timezone.utc)


def test_lane_seconds_direct_call() -> None:
    assert history_entry._lane_seconds("2026-01-01T00:00:00Z", MOMENT) == 60
    assert history_entry._lane_seconds("", MOMENT) is None
    assert history_entry._lane_seconds(None, MOMENT) is None
    assert history_entry._lane_seconds("not-a-date", MOMENT) is None
    assert history_entry._lane_seconds("2026-01-01T00:05:00Z", MOMENT) == 0
    assert text_module._lane_seconds("2026-01-01T00:00:00", MOMENT) == 60


def test_lane_count_age_and_node_direct_call() -> None:
    assert history_entry._lane_count_age({"n": 2, "oldest": "2026-01-01T00:00:00Z"}, MOMENT) == {
        "count": 2,
        "oldest_seconds": 60,
    }
    with pytest.raises(history_entry.HistoryError, match="unavailable"):
        history_entry._lane_count_age(None, MOMENT)
    with pytest.raises(history_entry.HistoryError, match="not a count"):
        history_entry._lane_count_age({"n": True, "oldest": None}, MOMENT)
    assert history_entry._lane_node(
        {"node_ref": "node-1", "n": 3, "oldest": "2026-01-01T00:00:00Z", "waiting": 1, "waiting_oldest": "2026-01-01T00:00:30Z"},
        MOMENT,
    ) == {"node_ref": "node-1", "open": 3, "oldest_seconds": 60, "waiting": 1, "waiting_oldest_seconds": 30}
    with pytest.raises(history_entry.HistoryError, match="names no node"):
        history_entry._lane_node({"node_ref": "", "n": 0, "waiting": 0}, MOMENT)
    with pytest.raises(history_entry.HistoryError, match="no waiting count"):
        history_entry._lane_node({"node_ref": "node-1", "n": 0, "waiting": -1}, MOMENT)


def test_conversation_list_search_and_preview_unchanged() -> None:
    from app.history import D1HistoryStore, PRODUCT_SCOPE_CHAT

    db = setup_database()
    store = D1HistoryStore(D1Sqlite(db))
    cid = asyncio.run(
        store.append_exchange(
            OWNER, None, "파디엠 견적 요청", "합성 응답 본문", product_scope=PRODUCT_SCOPE_CHAT
        )
    )
    asyncio.run(
        store.append_exchange(
            OWNER, None, "다른 주제", "다른 응답", product_scope=PRODUCT_SCOPE_CHAT
        )
    )
    listed = asyncio.run(store.list_conversations(OWNER, product_scope=PRODUCT_SCOPE_CHAT))
    assert cid in {row["id"] for row in listed} and len(listed) == 2
    hits = asyncio.run(store.search_conversations(OWNER, "견적", product_scope=PRODUCT_SCOPE_CHAT))
    assert [hit["id"] for hit in hits] == [cid]
    detail = asyncio.run(store.get_conversation(OWNER, cid, product_scope=PRODUCT_SCOPE_CHAT))
    assert detail is not None and detail["id"] == cid
    assert detail["messages"] == [
        {"role": "user", "content": "파디엠 견적 요청"},
        {"role": "assistant", "content": "합성 응답 본문"},
    ]
    db.close()
