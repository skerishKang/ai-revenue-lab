"""#5655: meeting-minutes and activity-book prompts must not be misclassified as
native calendar operations.

Regression focus: prompts containing incidental calendar vocabulary ("일정",
"생성", dates) inside writing tasks must reach general chat, while genuine
calendar create/read requests keep working.
"""
from __future__ import annotations

import sys

import pytest

sys.path.insert(0, ".")

from app import native_calendar_intent as nci


def _parse(text):
    return nci.parse_native_calendar_intent(text, timezone_name="Asia/Seoul")


MEETING_PROMPT = (
    "다음 회의 내용을 정리해 주세요.\n\n"
    "회의명: 2026 Q4 Community Planning\n"
    "참석자: CEO, PM, Community Lead\n"
    "회의 내용:\nDiscussed community sharing event plan, budget, and next quarter goals.\n\n"
    "다음 항목으로 정리해 주세요:\n"
    "1. 회의 요약 (3-5문장)\n"
    "2. 주요 논의사항 (bullet)\n"
    "3. 결정사항 (bullet)\n"
    "4. 후속 업무 (담당자/일정이 원문에 있으면 포함)\n"
    "5. 미해결 사항"
)

BOOK_PROMPT = (
    "다음은 사용자가 선택한 활동 기록 본문입니다. 각 기록의 이름을 출처로 유지하세요.\n\n"
    "[기록: 2026 Q4 Community Planning.txt]\n회의 요약: ...\n\n"
    "위 기록을 바탕으로 다음을 생성해 주세요:\n"
    "1. 책/활동집 제목 후보 3개\n"
    "2. 목차 (5-8장)\n"
    "3. 각 장별 원고 초안 (200-400자)\n"
    "4. 마무리 인사\n\n"
    "주의: 원본 기록에 없는 사건, 날짜, 발언을 사실처럼 추가하지 마세요."
)


def test_meeting_prompt_is_not_calendar():
    assert _parse(MEETING_PROMPT)["op"] == "none"


def test_book_prompt_is_not_calendar():
    assert _parse(BOOK_PROMPT)["op"] == "none"


def test_calendar_create_still_works():
    assert _parse("내일 오전 9시 회의 일정 등록해줘")["op"] == "create_appointment"


def test_calendar_read_still_works():
    assert _parse("이번 주 일정 보여줘")["op"] == "read"


def test_calendar_clarify_date_still_works():
    assert _parse("일정 등록해줘")["op"] == "clarify"


def test_calendar_clarify_range_still_works():
    assert _parse("일정 보여줘")["op"] == "clarify"


def test_general_chat_still_none():
    assert _parse("안녕하세요")["op"] == "none"


def test_reworded_meeting_prompts_are_not_calendar():
    variants = [
        "회의록 작성해줘",
        "회의 내용 요약해 주세요",
        "회의록을 만들어 주세요",
        "오늘 회의 정리해줘",
    ]
    for v in variants:
        assert _parse(v)["op"] == "none", v


def test_reworded_book_prompts_are_not_calendar():
    variants = [
        "활동집 만들어줘",
        "활동집 초안 작성해줘",
        "책 초안 만들어 주세요",
    ]
    for v in variants:
        assert _parse(v)["op"] == "none", v


from contextlib import contextmanager


@contextmanager
def _client():
    from test_4745_native_calendar_chat_claw_routes import client_factory

    with client_factory() as c:
        from test_4379_b62_owner_model_context import CaptureCompleted

        c.app.state.b14_client = CaptureCompleted()
        c.app.state.usage_gate_enforced = False
        yield c


@pytest.mark.parametrize("prompt", [MEETING_PROMPT, BOOK_PROMPT])
def test_chat_route_does_not_return_calendar_clarification(prompt):
    with _client() as c:
        r = c.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": prompt}], "timezone": "Asia/Seoul"},
            headers={"Origin": "https://chat.example.test"},
        )
        assert r.status_code == 200, r.text
        body = r.text
        assert "시작 시간을 알려주세요" not in body
        assert "일정 날짜를 더 구체적으로" not in body
        assert "조회할 일정 범위" not in body
        assert "시간대(예: Asia/Seoul)" not in body
        assert "Completed response" in body


def test_chat_route_calendar_create_still_works():
    with _client() as c:
        r = c.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": "내일 오전 9시 회의 일정 등록해줘"}], "timezone": "Asia/Seoul"},
            headers={"Origin": "https://chat.example.test"},
        )
        assert r.status_code == 200, r.text
        assert "일정이 등록" in r.text
