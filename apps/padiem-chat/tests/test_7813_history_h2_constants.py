"""T3 H2 회귀 — 상수·SQL 조각·제품·PC 범위가 `history.py` 재수출로 같은 결과를 낸다 (#7813).

소스 문자열이 아니라 실제 호출로 검증한다. 지역·모의만 사용한다(운영 DB·로그인·답변 생성 없음).
"""
from __future__ import annotations

import asyncio

import pytest

from app import history as history_entry
from app import history_constants as constants_module
from app import history_types as types_module

from _support.b66_conversation_isolation import D1Sqlite, OWNER, setup_database


def test_reexport_names_are_the_same_objects() -> None:
    for name in (
        "MAX_HISTORY_MESSAGE_CHARS",
        "MAX_MODEL_CONTEXT_BYTES",
        "MAX_HISTORY_TITLE_CHARS",
        "MAX_RECENT_CONVERSATIONS",
        "MAX_PROJECT_NAME_CHARS",
        "MAX_PROJECTS",
        "MAX_CLAW_RUNS",
        "MULTI_COMMAND_RUN_ACTIONS",
        "is_multi_command_action",
        "ORACLE_MESH_CLAIM_LEASE_SECONDS",
        "ORACLE_MESH_READ_ONLY_SQL",
        "ORACLE_MESH_CLAIMABLE_SQL",
        "ORACLE_MESH_UNREDELIVERABLE_SQL",
        "PC_CONFIRMATION_CARD_ACTIONS",
        "MAX_CLAW_HANDOFF_TRUSTED_REQUEST_CHARS",
        "PRODUCT_SCOPE_CHAT",
        "PRODUCT_SCOPE_B66",
        "KNOWN_PRODUCT_SCOPES",
        "_APPEND_EXCHANGE_SQL",
        "_APPEND_USER_MESSAGE_SQL",
        "_require_product_scope",
        "PC_SCOPE_NOTICE_LABELS",
        "strip_pc_scope_marker",
        "strip_pc_session_confirmation_marker",
        "pc_scope_notice",
    ):
        assert getattr(history_entry, name) is getattr(constants_module, name), name
    for name in ("MAX_RECENT_CONVERSATIONS", "MAX_PROJECTS", "MAX_CLAW_RUNS"):
        assert getattr(types_module, name) is getattr(constants_module, name), name


def test_constant_values_direct_call() -> None:
    assert history_entry.MAX_HISTORY_MESSAGE_CHARS == 8000
    assert history_entry.MAX_MODEL_CONTEXT_BYTES == 5_500_000
    assert history_entry.MAX_HISTORY_TITLE_CHARS == 80
    assert history_entry.MAX_RECENT_CONVERSATIONS == 30
    assert history_entry.MAX_PROJECT_NAME_CHARS == 80
    assert history_entry.MAX_PROJECTS == 50
    assert history_entry.MAX_CLAW_RUNS == 30
    assert history_entry.MULTI_COMMAND_RUN_ACTIONS == frozenset({"pc_files_query", "pc_browser_query"})
    assert history_entry.ORACLE_MESH_CLAIM_LEASE_SECONDS == 60
    assert history_entry.PC_CONFIRMATION_CARD_ACTIONS == frozenset(
        {"pc_command", "desktop_type", "pc_session_start", "pc_session_input"}
    )
    assert history_entry.MAX_CLAW_HANDOFF_TRUSTED_REQUEST_CHARS == 32000


def test_sql_fragments_direct_call() -> None:
    assert history_entry.ORACLE_MESH_READ_ONLY_SQL == "COALESCE(read_only, CASE WHEN kind='read' THEN 1 ELSE 0 END)"
    # 파생 SQL 조각은 읽기 전용 조각을 값으로 품는다(원본 f-문자열 결과 그대로).
    assert history_entry.ORACLE_MESH_READ_ONLY_SQL in history_entry.ORACLE_MESH_CLAIMABLE_SQL
    assert history_entry.ORACLE_MESH_READ_ONLY_SQL in history_entry.ORACLE_MESH_UNREDELIVERABLE_SQL
    assert "state='pending'" in history_entry.ORACLE_MESH_UNREDELIVERABLE_SQL
    assert "INSERT INTO messages" in history_entry._APPEND_EXCHANGE_SQL
    assert "n + 1" in history_entry._APPEND_EXCHANGE_SQL
    assert "INSERT INTO messages" in history_entry._APPEND_USER_MESSAGE_SQL
    assert "n + 1" not in history_entry._APPEND_USER_MESSAGE_SQL


def test_multi_command_action_direct_call() -> None:
    assert history_entry.is_multi_command_action("pc_files_query") is True
    assert history_entry.is_multi_command_action("pc_browser_query") is True
    assert history_entry.is_multi_command_action("pc_command") is False
    assert history_entry.is_multi_command_action(None) is False
    assert constants_module.is_multi_command_action("pc_files_query") is True


def test_product_scope_direct_call() -> None:
    assert history_entry.PRODUCT_SCOPE_CHAT == "b62-chat"
    assert history_entry.PRODUCT_SCOPE_B66 == "b66-quote"
    assert history_entry.KNOWN_PRODUCT_SCOPES == frozenset({"b62-chat", "b66-quote"})
    assert history_entry._require_product_scope("b62-chat") == "b62-chat"
    assert history_entry._require_product_scope("b66-quote") == "b66-quote"
    with pytest.raises(history_entry.HistoryForbidden, match="product scope"):
        history_entry._require_product_scope("unknown")
    with pytest.raises(history_entry.HistoryForbidden, match="product scope"):
        history_entry._require_product_scope(None)


def test_pc_scope_marker_and_notice_direct_call() -> None:
    assert history_entry.strip_pc_scope_marker("PC 범위 안내\n<!--pc_scope:{\"admitted\":\"x\"}-->") == "PC 범위 안내"
    assert history_entry.strip_pc_scope_marker("일반 답변") == "일반 답변"
    assert history_entry.strip_pc_session_confirmation_marker("본문\n<!--pc-session-confirm:{\"x\":1}-->") == "본문"
    assert history_entry.pc_scope_notice({"admitted": "files"}) == "요청한 파일의 목록과 내용을 확인합니다."
    assert history_entry.pc_scope_notice({"admitted": "files_list"}) == "목록만 조회합니다. 파일 내용은 읽지 않습니다."
    assert history_entry.pc_scope_notice({"admitted": "unknown"}) is None
    assert history_entry.pc_scope_notice("not-a-dict") is None
    assert history_entry.PC_SCOPE_NOTICE_LABELS["none"] == "허용된 PC 작업 범위를 확인하지 못했습니다."


def test_conversation_append_uses_moved_sql_unchanged() -> None:
    from app.history import D1HistoryStore, PRODUCT_SCOPE_CHAT

    db = setup_database()
    store = D1HistoryStore(D1Sqlite(db))
    cid = asyncio.run(
        store.append_exchange(
            OWNER, None, "파디엠 견적 요청", "합성 응답 본문", product_scope=PRODUCT_SCOPE_CHAT
        )
    )
    detail = asyncio.run(store.get_conversation(OWNER, cid, product_scope=PRODUCT_SCOPE_CHAT))
    assert detail is not None and detail["id"] == cid
    assert detail["messages"] == [
        {"role": "user", "content": "파디엠 견적 요청"},
        {"role": "assistant", "content": "합성 응답 본문"},
    ]
    # 제품 범위 밖에서는 같은 대화도 보이지 않는다.
    assert asyncio.run(store.get_conversation(OWNER, cid, product_scope=history_entry.PRODUCT_SCOPE_B66)) is None
    db.close()
