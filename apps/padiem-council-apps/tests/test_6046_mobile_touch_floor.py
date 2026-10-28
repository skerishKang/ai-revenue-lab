"""#6046 잔여 실서비스 E2E에서 실측한 터치 대상 결함.

390x844 실측(innerWidth 355 / dpr 1.10): `#councilCountry` 32.0px, 활동집 기록
체크박스 13.0px(UA 기본) 로 손가락 대상보다 작았다.

두 항목의 처리가 다른 이유는 실측으로 정했다:
- 체크박스는 행 자체가 44px 하한(#5942)이라 어디서도 레이아웃을 움직이지 않는다 -> 전역.
- 언어 선택을 전역 44px 하한에 넣으면 데스크톱 상단바가 55.60 -> 68.88px(+13.28)로
  자랐다(A/B 실측). 요청되지 않은 시각 변경이라 좁은 화면에서만 올린다.
"""
from __future__ import annotations

import re
from pathlib import Path

CSS = (Path(__file__).resolve().parents[1] / "static" / "council-app.css").read_text(encoding="utf-8")


def _media_block(width: str) -> str:
    m = re.search(rf"@media \(max-width: {width}px\)\s*\{{(.*?)\n\}}", CSS, re.S)
    assert m, f"the @media (max-width: {width}px) block must exist"
    return m.group(1)


def test_the_country_select_gets_the_touch_target_only_where_it_was_measured():
    block = _media_block("900")
    rule = re.search(r"\.council-country select\s*\{\s*min-height:\s*(\d+)px", block)
    assert rule, "the narrow-viewport block must raise the language select"
    assert int(rule.group(1)) >= 44


def test_the_country_select_is_not_in_the_global_floor():
    """전역 #5942 하한에 넣으면 데스크톱 상단바가 13.28px 자란다 — 실측으로 배제했다."""
    floor = re.search(r"(\.council-archive-item button,[^{]*)\{[^}]*min-height:\s*44px", CSS, re.S)
    assert floor, "the global 44px floor block must stay"
    assert ".council-country" not in floor.group(1)


def test_the_book_check_has_a_real_target_size():
    rule = re.search(r"\.council-book-check\s*\{([^}]*)\}", CSS, re.S)
    assert rule, "the record checkbox needs an explicit size, the UA default is 13px"
    body = rule.group(1)
    for prop in ("width", "height"):
        m = re.search(rf"{prop}:\s*(\d+)px", body)
        assert m and int(m.group(1)) >= 24, f"{prop} must reach the 24px minimum"
