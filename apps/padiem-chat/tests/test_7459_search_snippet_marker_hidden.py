"""#7459 — 검색 결과 미리보기에도 내부 pc_scope 마커가 나가지 않는다.

#7465가 대화 불러오기(get_conversation) 투영에서 마커를 벗겨낸 뒤에도, 검색
결과의 스니펫은 같은 저장 원문을 다른 투영으로 내보내는 지점이라
`<!--pc_scope:{...}-->` 글자가 미리보기에 그려질 수 있었다. 검색어가 스코프
기록(공지 문구 또는 마커 내부 JSON)에 걸리면 hit이 스코프 기록 행이 되고,
120자 스니펫 창이 마커를 포함하기 때문이다.

투영 단계에서 벗겨내므로 이미 저장된 기록에도 효과가 난다. 검색 자체는 원문으로
계속 동작한다 — 마커 내부 토큰으로 대화를 "찾는" 것은 막지 않고, "보여주지
않는" 것만 규정한다.

진짜 저장 경로(pin_pc_run_scope)로 스코프 기록을 만들어 검색까지 돌린다.
"""
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from app.history import (
    D1HistoryStore,
    PC_SCOPE_NOTICE_LABELS,
    PRODUCT_SCOPE_CHAT,
)
from _support.b66_conversation_isolation import D1Sqlite

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"

OWNER = "usr_" + "c" * 32
RUN = "chat_pcq_" + "e" * 32

# ops 안의 토큰은 마커 내부 JSON에만 존재한다. 이 검색어는 공지 문구에는
# 걸리지 않고 마커에만 걸리므로, hit이 스코프 기록 행이 된다. 저장 시
# json.dumps가 비ASCII를 \u 이스케이프하므로 토큰은 ASCII여야 원문 그대로
# 매칭된다.
MARKER_ONLY_TOKEN = "documents/quotes"


def _database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    for path in sorted(MIGRATIONS.glob("*.sql")):
        connection.executescript(path.read_text(encoding="utf-8"))
    connection.execute(
        "INSERT INTO users (id,auth_provider,provider_subject,email,created_at,updated_at) "
        "VALUES (?,'google',?,'owner@example.test','2026-11-11','2026-11-11')",
        (OWNER, "subject-" + OWNER),
    )
    connection.commit()
    return connection


def _store(connection: sqlite3.Connection) -> D1HistoryStore:
    return D1HistoryStore(D1Sqlite(connection))


def _stage_turn_with_pinned_scope(store: D1HistoryStore, connection: sqlite3.Connection) -> str:
    conversation_id = asyncio.run(store.append_exchange(
        OWNER, None, "PC 파일 목록만 보여줘", "승인된 폴더의 목록을 확인했습니다.",
        product_scope=PRODUCT_SCOPE_CHAT,
    ))
    connection.execute(
        "INSERT INTO claw_run_history (id,user_id,run_id,channel,action,title,status,"
        "created_at,updated_at,conversation_id,workspace_id) "
        "VALUES (?,?,?,'web','pc_files_query','외부 AI 도구 요청','pending',"
        "'2026-11-11','2026-11-11',?,NULL)",
        ("rh_" + RUN[-8:], OWNER, RUN, conversation_id),
    )
    connection.commit()
    # 운영과 같은 저장 경로: 공지 문구 + "\n<!--pc_scope:{...}-->" 한 행.
    asyncio.run(store.pin_pc_run_scope(
        user_id=OWNER, run_id=RUN,
        claim={"version": 1, "requested": "files", "admitted": "files_list",
               "source": "declared", "ops": [MARKER_ONLY_TOKEN],
               "app_id": "padiem-chat"},
    ))
    return conversation_id


def _search(store: D1HistoryStore, query: str) -> list[dict]:
    return asyncio.run(store.search_conversations(
        OWNER, query, product_scope=PRODUCT_SCOPE_CHAT))


def test_a_query_that_lands_on_the_scope_record_keeps_the_marker_out_of_the_snippet():
    connection = _database()
    try:
        store = _store(connection)
        conversation_id = _stage_turn_with_pinned_scope(store, connection)
        hits = _search(store, MARKER_ONLY_TOKEN)
        # The conversation stays findable through its stored record.
        assert [hit["id"] for hit in hits] == [conversation_id]
        snippet = hits[0]["snippet"]
        assert "<!--pc_scope:" not in snippet
        assert MARKER_ONLY_TOKEN not in snippet
        # What remains is the display notice wording, never the internal record.
        assert PC_SCOPE_NOTICE_LABELS["files_list"] in snippet
    finally:
        connection.close()


def test_a_query_on_the_notice_wording_also_stays_clean():
    connection = _database()
    try:
        store = _store(connection)
        conversation_id = _stage_turn_with_pinned_scope(store, connection)
        hits = _search(store, "목록만 조회합니다")
        assert [hit["id"] for hit in hits] == [conversation_id]
        snippet = hits[0]["snippet"]
        assert "<!--pc_scope:" not in snippet
        assert "목록만 조회합니다" in snippet
    finally:
        connection.close()


def test_the_session_confirmation_marker_stays_out_of_snippets_too():
    """The pc_scope strip chains the older pc-session-confirm strip: one
    projection call must keep handling both marker shapes."""
    connection = _database()
    try:
        store = _store(connection)
        conversation_id = asyncio.run(store.append_exchange(
            OWNER, None, "세션 확인 질문",
            "확인을 기록했습니다.\n<!--pc-session-confirm:{\"nonce\":\"n-7459\"}-->",
            product_scope=PRODUCT_SCOPE_CHAT,
        ))
        hits = _search(store, "n-7459")
        assert [hit["id"] for hit in hits] == [conversation_id]
        snippet = hits[0]["snippet"]
        assert "<!--pc-session-confirm:" not in snippet
        assert "<!--pc_scope:" not in snippet
    finally:
        connection.close()


def test_loaded_conversation_body_stays_marker_free_with_the_real_pin_path():
    connection = _database()
    try:
        store = _store(connection)
        conversation_id = _stage_turn_with_pinned_scope(store, connection)
        loaded = asyncio.run(store.get_conversation(
            OWNER, conversation_id, product_scope=PRODUCT_SCOPE_CHAT))
        assert loaded is not None
        for message in loaded["messages"]:
            assert "<!--pc_scope:" not in message["content"]
            assert "<!--pc-session-confirm:" not in message["content"]
        # The notice wording itself is the #5573 display decision and stays.
        assert any(
            PC_SCOPE_NOTICE_LABELS["files_list"] in message["content"]
            for message in loaded["messages"]
        )
    finally:
        connection.close()
