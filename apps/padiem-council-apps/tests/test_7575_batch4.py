# -*- coding: utf-8 -*-
"""#7575 batch 4 — source-grounded book draft, PC import help, quick period."""
from __future__ import annotations

from _council_module import run


def test_book_fact_check_uses_a_second_meeting_stream_request():
    seen = run("book_factcheck")
    ok = seen["ok"]
    assert ok["calls"] == 2, ok
    assert ok["firstPromptHasSource"] and ok["secondPromptHasSource"], ok
    assert ok["secondPromptHasDraft"], ok
    assert ok["secondUtil"] == "meeting", ok
    assert ok["output"] == "고친 초안입니다. 교체하기로 했고 설치를 검토하기로 했다.", ok
    assert "고친 곳" not in ok["output"], ok
    assert ok["fact"] == "원문과 대조해 2곳을 고쳤습니다", ok
    assert seen["pageErrors"] == [], seen


def test_failed_fact_check_keeps_the_first_draft_and_warns():
    seen = run("book_factcheck")
    fail = seen["fail"]
    assert fail["calls"] == 2, fail
    assert fail["output"] == "초안입니다. 기한이 경과된 상태입니다.", fail
    assert fail["fact"] == "원문 대조를 하지 못했습니다. 사실관계를 직접 확인해 주세요", fail


def test_pc_import_help_lines_are_on_the_right_screens():
    seen = run("meeting_pc_help")
    assert seen["meetingHasMeetingLine"] is True, seen
    assert seen["snsHasMeetingLine"] is False, seen
    assert seen["snsHasOldLine"] is True, seen
    assert seen["speechHasOldLine"] is True, seen
    assert seen["pageErrors"] == [], seen


def test_quick_period_selects_records_on_the_first_click():
    seen = run("quick_period_first_click")
    assert seen["picks"] == 4, seen
    assert seen["checks"][0]["checked"] is True, seen
    assert seen["checks"][1]["checked"] is False, seen
    assert seen["status"].startswith("1건을 선택했습니다"), seen
    assert seen["start"] and seen["end"] and seen["start"] <= seen["end"], seen
    assert seen["pageErrors"] == [], seen
