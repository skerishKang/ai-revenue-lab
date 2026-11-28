# -*- coding: utf-8 -*-
"""#8824 — stricter fact-check instructions and clean book download names."""
from __future__ import annotations

from datetime import datetime

from _council_module import run


def test_fact_check_prompt_carries_the_concrete_bad_examples():
    seen = run("book_factcheck")["ok"]
    prompt = seen["secondPrompt"]
    for phrase in (
        "'확인한다'면 '수리한다·완료'로 바꾸지 마라",
        "'다시 정하기로 했다'면 '예고·확정'으로 바꾸지 마라",
        "원문에 없는 끝 날짜·기간(예: ~11월 말까지)을 만들지 마라",
        "'계획·검토·예정·확인 예정'은 그 낱말 그대로 둘 것",
    ):
        assert phrase in prompt, (phrase, prompt)
    assert seen["calls"] == 2 and seen["secondUtil"] == "meeting", seen


def test_book_download_names_strip_markdown_and_heading_words():
    seen = run("book_filename")
    for name in seen["heading"]:
        assert "#" not in name, name
        assert "제목 후보" not in name, name
        assert not name.startswith("활동집 - 1."), name
        assert name.startswith(f"활동집_2026-11-01~2026-11-30_{datetime.now().strftime('%Y-%m-%d')}."), name
    # an empty title falls back to the same dated name
    for name in seen["empty"]:
        assert name.startswith(f"활동집_2026-11-01~2026-11-30_{datetime.now().strftime('%Y-%m-%d')}."), name
    # a real title is still kept as the file name
    for name in seen["real"]:
        assert name.startswith("활동집 - 함께 만드는 가온동 안전망."), name
    assert seen["pageErrors"] == [], seen
