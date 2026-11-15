"""#7784: pure writing requests must never force a web retrieval.

A drafting verb (공지·축사·이메일·요약·번역 등) dates the draft, not the
world. A freshness word that only states the announcement date
("오늘 공지 문구 써줘") must not trigger a search, while an explicit
"검색해서" request and a latest-info question keep searching.
"""
from __future__ import annotations

import pytest

from padiem_ai_core.search_decision import SearchDisposition, decide_search


@pytest.mark.parametrize(
    "prompt",
    [
        "직원 공지 문구 써 줘",
        "직원 공지 문구 써줘",
        "오늘 직원 공지 문구 써줘",
        "오늘 공지 문구 써줘",
        "오늘 축사 써줘",
        "오늘 이메일 써줘",
        "오늘 안내문 써줘",
        "공지 써줘",
        "공지 작성해줘",
        "안내문 써줘",
        "축사 써줘",
        "이메일 써줘",
        "이 글 요약해줘",
        "오늘 회의록 요약해줘",
        "이 문장을 영어로 번역해줘",
        "공연 문장 번역해줘",
        "이 문장 다듬어줘",
    ],
)
def test_pure_writing_requests_never_search(prompt: str) -> None:
    decision = decide_search(prompt)
    assert decision.disposition is SearchDisposition.NO_SEARCH
    assert decision.requires_search is False
    assert decision.evidence_required is False
    assert decision.reason == "writing_request_no_search"


@pytest.mark.parametrize(
    "prompt",
    [
        "오늘 AI 뉴스 알려줘",
        "최신 뉴스 알려줘",
        "원달러 환율 알려줘",
        "오늘 광주 날씨 알려줘",
        "오늘 코스피 지수 알려줘",
    ],
)
def test_latest_info_questions_keep_searching(prompt: str) -> None:
    decision = decide_search(prompt)
    assert decision.disposition is SearchDisposition.MUST_SEARCH
    assert decision.requires_search is True
    assert decision.evidence_required is True


@pytest.mark.parametrize(
    "prompt",
    [
        "직원 공지 문구 검색해서 써줘",
        "검색해서 알려줘 직원 공지 문구",
        "오늘 공개된 보도자료를 찾아서 요약해줘",
        "환율 공지 문구 써줘 알려줘",
    ],
)
def test_explicit_search_wins_over_a_writing_cue(prompt: str) -> None:
    decision = decide_search(prompt)
    assert decision.disposition is SearchDisposition.MUST_SEARCH
    assert decision.requires_search is True


def test_a_current_news_summary_keeps_searching() -> None:
    # Summarizing today's news needs the news itself; only a summary of the
    # user's own text is source-bound.
    decision = decide_search("오늘 뉴스 요약해줘")
    assert decision.disposition is SearchDisposition.MUST_SEARCH
    assert decision.requires_search is True
