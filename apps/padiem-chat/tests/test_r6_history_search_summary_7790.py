"""R6 두 번째 구역 회귀 — 검색 보조와 요약 합병이 `history.py` 재수출로 같은 결과를 낸다 (#7790).

소스 문자열이 아니라 실제 호출로 검증한다. 지역·모의만 사용한다(운영 DB·로그인·답변 생성 없음).
"""
from __future__ import annotations

import asyncio

import pytest

from app import history as history_entry
from app import history_run_summary as summary_module
from app import history_search as search_module

from test_b66_conversation_isolation_4657 import D1Sqlite, OWNER, setup_database


def test_reexport_names_are_the_same_objects() -> None:
    for name in (
        "MAX_CONVERSATION_SEARCH_QUERY_CHARS",
        "MAX_CONVERSATION_SEARCH_RESULTS",
        "MAX_CONVERSATION_SEARCH_SCAN_ROWS",
        "MAX_CONVERSATION_SEARCH_SNIPPET_CHARS",
        "_normalize_search_query",
        "_search_snippet",
    ):
        assert getattr(history_entry, name) is getattr(search_module, name), name
    for name in ("MAX_RUN_RESULT_SUMMARY_CHARS", "_merge_run_result_summaries"):
        assert getattr(history_entry, name) is getattr(summary_module, name), name


def test_normalize_search_query_direct_call() -> None:
    assert history_entry._normalize_search_query("  hello   world \n") == "hello world"
    assert history_entry._normalize_search_query("   ") == ""
    assert history_entry._normalize_search_query(None) == ""
    assert len(history_entry._normalize_search_query("가" * 500)) == 80


def test_search_snippet_direct_call() -> None:
    body = "앞" * 400 + " 파디엠 견적 " + "뒤" * 400
    snippet = history_entry._search_snippet(body, "파디엠 견적")
    assert "파디엠 견적" in snippet
    assert len(snippet) <= 122
    assert snippet.startswith("…") and snippet.endswith("…")
    assert history_entry._search_snippet(None, "x") == ""
    assert history_entry._search_snippet("", "x") == ""


def test_merge_run_result_summaries_direct_call() -> None:
    assert history_entry._merge_run_result_summaries(None, "a") == "a"
    assert history_entry._merge_run_result_summaries("a", "b") == "a; b"
    # 순서 유지, 중복 없음
    assert history_entry._merge_run_result_summaries("a; b", "a") == "a; b"
    assert history_entry._merge_run_result_summaries("a", "a") == "a"
    assert history_entry._merge_run_result_summaries("", "") == ""
    assert history_entry._merge_run_result_summaries(None, "") == ""
    # 상한
    long_stored = "x" * 199
    assert len(history_entry._merge_run_result_summaries(long_stored, "y" * 10)) == 200


def test_merge_via_new_module_is_same_behavior() -> None:
    assert summary_module._merge_run_result_summaries("a; b", "c") == "a; b; c"
    assert search_module._normalize_search_query("  x  y ") == "x y"


def test_conversation_list_search_and_preview_unchanged() -> None:
    from app.history import D1HistoryStore, PRODUCT_SCOPE_CHAT

    db = setup_database()
    store = D1HistoryStore(D1Sqlite(db))
    owner = OWNER
    cid = asyncio.run(
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
    assert cid in {row["id"] for row in listed} and len(listed) == 2
    hits = asyncio.run(store.search_conversations(owner, "견적", product_scope=PRODUCT_SCOPE_CHAT))
    assert [hit["id"] for hit in hits] == [cid]
    detail = asyncio.run(store.get_conversation(owner, cid, product_scope=PRODUCT_SCOPE_CHAT))
    assert detail is not None and detail["id"] == cid
    assert detail["messages"] == [
        {"role": "user", "content": "파디엠 견적 요청"},
        {"role": "assistant", "content": "합성 응답 본문"},
    ]
    db.close()


@pytest.mark.parametrize(
    "stored, addition, expected",
    [
        (None, "실패했습니다", "실패했습니다"),
        ("ok", "실패했습니다", "ok; 실패했습니다"),
    ],
)
def test_merge_keeps_failures(stored, addition, expected) -> None:
    assert history_entry._merge_run_result_summaries(stored, addition) == expected
