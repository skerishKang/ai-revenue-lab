"""#6046 잔여 실서비스 E2E에서 실측한 터치 대상 결함.

390x844 에서 `#councilCountry` 는 32.0px, 활동집 기록 선택 체크박스는 13.0px였다.
이 파일의 #5942 규칙은 "하한을 한 곳에만 적는다" 이므로 예외 미디어 쿼리를 늘리는
대신 그 하한 목록에 넣는다.
"""
from __future__ import annotations

import re
from pathlib import Path

CSS = (Path(__file__).resolve().parents[1] / "static" / "council-app.css").read_text(encoding="utf-8")


def _floor_rules() -> str:
    m = re.search(r"\.council-archive-item button,[^{]*\{[^}]*min-height:\s*44px;[^}]*\}", CSS, re.S)
    assert m, "the single 44px floor block must stay"
    return m.group(0)


def test_the_country_select_is_inside_the_44px_floor():
    assert ".council-country select" in _floor_rules()


def test_the_book_check_has_a_real_target_size():
    rule = re.search(r"\.council-book-check\s*\{([^}]*)\}", CSS, re.S)
    assert rule, "the record checkbox needs an explicit size, the UA default is 13px"
    body = rule.group(1)
    for prop in ("width", "height"):
        m = re.search(rf"{prop}:\s*(\d+)px", body)
        assert m and int(m.group(1)) >= 24, f"{prop} must reach the 24px WCAG minimum"


def test_floor_is_stated_once_not_duplicated_per_media_query():
    """하한을 모바일 블록에 다시 적으면 데스크톱은 그대로 32px 로 남는다."""
    mobile = re.search(r"@media \(max-width: 900px\)\s*\{(.*?)\n\}", CSS, re.S)
    assert mobile and ".council-country select" not in mobile.group(1)
    narrow = re.search(r"@media \(max-width: 390px\)\s*\{(.*?)\n\}", CSS, re.S)
    assert narrow and "min-height" not in narrow.group(1)
