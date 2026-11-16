"""T3 H3 회귀 — ID·날짜·미리보기·행 변환이 `history.py` 재수출로 같은 결과를 낸다 (#7813).

소스 문자열이 아니라 실제 호출로 검증한다. 지역·모의만 사용한다(운영 DB·로그인·답변 생성 없음).
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone

import pytest

from app import history as history_entry
from app import history_ids as ids_module
from app import history_rows as rows_module
from app import history_text as text_module

from test_b66_conversation_isolation_4657 import D1Sqlite, OWNER, setup_database


def test_reexport_names_are_the_same_objects() -> None:
    for name in (
        "_CLAW_HANDOFF_TRUSTED_REQUEST_KEYS",
        "_user_id",
        "_password_user_id",
        "_chat_id",
        "_message_id",
        "GENERAL_ANSWER_MESSAGE_SALT",
        "MODEL_ONLY_RUN_ACTION",
        "general_answer_message_id",
        "_message_reference",
        "_project_id",
        "_run_history_id",
        "_handoff_id",
        "_handoff_trusted_request_json",
        "_parse_handoff_expiry",
        "_handoff_expired",
        "_validate_hex_id",
        "validate_conversation_id",
        "validate_project_id",
        "validate_chat_pc_run_id",
        "validate_project_fields",
        "build_project_context",
    ):
        assert getattr(history_entry, name) is getattr(ids_module, name), name
    for name in (
        "_iso",
        "_now_iso",
        "_confirmation_card_cutoff",
        "_expire_stale_confirmation_cards_rule",
        "expire_stale_confirmation_cards_for_all_owners",
        "HISTORY_PREVIEW_SUFFIX",
        "_bounded_text",
        "_title_from_user_text",
        "_is_bounded_preview",
        "_lane_seconds",
        "_lane_count_age",
        "_lane_node",
    ):
        assert getattr(history_entry, name) is getattr(text_module, name), name
    for name in (
        "_changed_rows",
        "_batch_returned_row",
        "_row_to_dict",
        "_rows_from_result",
        "_project_from_row",
        "_run_history_session",
        "_run_history_public",
        "_tagged",
    ):
        assert getattr(history_entry, name) is getattr(rows_module, name), name


def test_id_generation_direct_call() -> None:
    assert history_entry._user_id("subject-1") == "usr_" + hashlib.sha256(b"google:subject-1").hexdigest()[:32]
    assert history_entry._password_user_id("UserName") == "usr_" + hashlib.sha256(b"password:username").hexdigest()[:32]
    chat_id = history_entry._chat_id()
    assert chat_id.startswith("chat_") and len(chat_id) == 5 + 32
    message_id = history_entry._message_id()
    assert message_id.startswith("msg_") and len(message_id) == 4 + 32
    assert history_entry._project_id().startswith("proj_")
    assert history_entry._run_history_id().startswith("crh_")
    assert history_entry._handoff_id().startswith("clh_")
    assert ids_module._chat_id() != chat_id


def test_general_answer_and_message_reference_direct_call() -> None:
    expected = "msg_ltr_" + hashlib.sha256(b"claw-general-answer:v1:run-1").hexdigest()[:40]
    assert history_entry.general_answer_message_id("run-1") == expected
    assert history_entry.GENERAL_ANSWER_MESSAGE_SALT == "claw-general-answer:v1"
    assert history_entry.MODEL_ONLY_RUN_ACTION == "general"
    with pytest.raises(history_entry.HistoryError, match="run_id is required"):
        history_entry.general_answer_message_id("")
    assert history_entry._message_reference("msg_ltr_abc-1") == "msg_ltr_abc-1"
    with pytest.raises(history_entry.HistoryError, match="bounded safe reference"):
        history_entry._message_reference("bad id!")


def test_handoff_trusted_request_direct_call() -> None:
    trusted = {"app_id": "app-1", "messages": [{"role": "user", "content": "안녕"}], "session_id": "s-1"}
    encoded, fingerprint = history_entry._handoff_trusted_request_json(trusted)
    assert fingerprint == hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    with pytest.raises(history_entry.HistoryError, match="outside the closed handoff shape"):
        history_entry._handoff_trusted_request_json({**trusted, "extra": 1})
    with pytest.raises(history_entry.HistoryError, match="must be an object"):
        history_entry._handoff_trusted_request_json("not-a-dict")


def test_identifier_validation_direct_call() -> None:
    conversation = "chat_" + "a" * 32
    assert history_entry.validate_conversation_id(conversation) == conversation
    assert history_entry.validate_conversation_id(None) is None
    assert history_entry.validate_project_id("proj_" + "b" * 32) == "proj_" + "b" * 32
    assert history_entry.validate_chat_pc_run_id("chat_pcq_" + "c" * 32) == "chat_pcq_" + "c" * 32
    with pytest.raises(ValueError, match="conversation_id"):
        history_entry.validate_conversation_id("chat_short")
    with pytest.raises(ValueError, match="project_id"):
        history_entry.validate_project_id(123)
    name, instructions = history_entry.validate_project_fields("  내 프로젝트  이름 ", " 지침 ")
    assert (name, instructions) == ("내 프로젝트 이름", "지침")
    with pytest.raises(ValueError, match="80자"):
        history_entry.validate_project_fields("가" * 81)


def test_build_project_context_direct_call() -> None:
    empty = history_entry.ProjectProfile("proj_1", "제목", "", "t0", "t1")
    assert history_entry.build_project_context(empty) == "현재 프로젝트: 제목"
    filled = history_entry.ProjectProfile("proj_1", "제목", "선호 지침", "t0", "t1")
    context = history_entry.build_project_context(filled)
    assert "제목" in context and "선호 지침" in context


def test_handoff_expiry_direct_call() -> None:
    moment = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert history_entry._parse_handoff_expiry("2026-01-02T00:00:00Z") == datetime(2026, 1, 2, tzinfo=timezone.utc)
    assert history_entry._parse_handoff_expiry("2026-01-02T00:00:00") is None
    assert history_entry._parse_handoff_expiry("") is None
    assert history_entry._handoff_expired("2025-12-31T00:00:00Z", moment) is True
    assert history_entry._handoff_expired("2026-01-02T00:00:00Z", moment) is False
    assert history_entry._handoff_expired("bad", moment) is True


MOMENT = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def test_date_helpers_direct_call() -> None:
    assert history_entry._iso(MOMENT) == "2026-01-01T12:00:00.000Z"
    assert history_entry._now_iso().endswith("Z")
    cutoff = history_entry._confirmation_card_cutoff(MOMENT)
    assert cutoff == "2026-01-01T11:50:00.000Z"  # 600초 전
    condition, values = history_entry._expire_stale_confirmation_cards_rule(MOMENT)
    assert "status=?" in condition and "created_at<?" in condition
    assert values[-1] == cutoff
    assert text_module._iso(MOMENT) == "2026-01-01T12:00:00.000Z"


def test_preview_and_title_direct_call() -> None:
    assert history_entry._bounded_text("  hello  ", "label") == "hello"
    assert history_entry._bounded_text("  keep  ", "label", preserve_edges=True) == "  keep  "
    long_text = "가" * 9000
    bounded = history_entry._bounded_text(long_text, "label")
    assert len(bounded) == 8000 and bounded.endswith(history_entry.HISTORY_PREVIEW_SUFFIX)
    assert history_entry._is_bounded_preview(bounded) is True
    assert history_entry._is_bounded_preview("short") is False
    with pytest.raises(history_entry.HistoryError, match="is empty"):
        history_entry._bounded_text("   ", "label")
    assert history_entry._title_from_user_text("첫 문장입니다. 나머지는 뒤에") == "첫 문장입니다."
    assert history_entry._title_from_user_text("") == "새 대화"
    assert len(history_entry._title_from_user_text("가" * 200)) == 80


def test_row_conversion_direct_call() -> None:
    assert history_entry._changed_rows(None) == 0
    assert history_entry._changed_rows({"meta": {"changes": 3}}) == 3
    assert history_entry._changed_rows({"meta": {"changes": True}}) == 0
    assert history_entry._changed_rows({"meta": {"changes": -2}}) == 0
    assert history_entry._row_to_dict(None) is None
    assert history_entry._row_to_dict({"a": 1}) == {"a": 1}
    assert history_entry._rows_from_result({"results": [{"a": 1}, None, {"b": 2}]}) == [{"a": 1}, {"b": 2}]
    assert history_entry._rows_from_result(None) == []
    assert history_entry._batch_returned_row(None, 0) is None
    assert history_entry._batch_returned_row([{"results": [{"id": "x"}]}], 0) == {"id": "x"}
    project = history_entry._project_from_row({"id": "p1", "name": "n", "instructions": "i", "created_at": "c", "updated_at": "u"})
    assert project == history_entry.ProjectProfile("p1", "n", "i", "c", "u")
    session = history_entry._run_history_session({"conversation_id": "chat_" + "a" * 32})
    assert session == {"conversation_id": "chat_" + "a" * 32}
    assert history_entry._run_history_session({"conversation_id": "bad"}) is None
    public = history_entry._run_history_public(
        {"run_id": "r1", "channel": "web", "action": "act", "title": "t", "status": "done",
         "created_at": "c", "updated_at": "u", "result_summary": None, "conversation_id": "chat_" + "a" * 32}
    )
    assert public["run_id"] == "r1" and public["session"] == session and public["artifact"] is None
    tagged = history_entry._tagged({"user_id": "usr_1", "dispatch_id": "d1"})
    assert isinstance(tagged, history_entry.VerifiedDispatch) and tagged.verified_for == "usr_1"


def test_conversation_append_uses_moved_helpers_unchanged() -> None:
    from app.history import D1HistoryStore, PRODUCT_SCOPE_CHAT

    db = setup_database()
    store = D1HistoryStore(D1Sqlite(db))
    cid = asyncio.run(
        store.append_exchange(
            OWNER, None, "파디엠 견적 요청", "합성 응답 본문", product_scope=PRODUCT_SCOPE_CHAT
        )
    )
    listed = asyncio.run(store.list_conversations(OWNER, product_scope=PRODUCT_SCOPE_CHAT))
    assert cid in {row["id"] for row in listed}
    detail = asyncio.run(store.get_conversation(OWNER, cid, product_scope=PRODUCT_SCOPE_CHAT))
    assert detail is not None and detail["messages"] == [
        {"role": "user", "content": "파디엠 견적 요청"},
        {"role": "assistant", "content": "합성 응답 본문"},
    ]
    db.close()
