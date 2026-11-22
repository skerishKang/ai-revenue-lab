"""#8056 / #8316 — 모바일 셸(≤920px)에서 고침 알림이 흐름 안에서 자리를 차지한다.

390 폭 홈에서 .feedback-notice 의 고정 배치 규칙이 '안녕하세요. 무엇을
도와드릴까요?' 인사말 제목을 덧대는 결함(#8056)을 잡는다. 계약 3가지:

1. 데스크톱 규칙은 그대로다 — base .feedback-notice 는 position:fixed 유지
   (1440 우측 위 띄움은 바뀌지 않는다).
2. (max-width: 920px) 범위에서는 position:static 으로 흐름에 들어와 자리를
   차지하고, 고정 배치의 덮기 좌표(top·right)를 다시 선언하지 않는다.
3. aside#feedbackNotice 는 상단 topbar 다음, 화면 섹션들 앞에 놓여 흐름
   배치가 인사말 위에서 시작되도록 한다. hidden 일 때는 자리를 차지하지 않는다.

기대값 문자열은 _support 모듈에 두어 이 시험은 원문 글자 대신 파싱된 구조로
단언한다(#8060 규칙).
"""
from __future__ import annotations

import re
from pathlib import Path

from _support.mobile_notice_expectations import (
    ARIA_LIVE, FIXED, HIDDEN, HIDDEN_RULE, MARGIN, MAX_WIDTH, NONE,
    POSITION, RIGHT, ROLE_STATUS, STATIC, TOP, MOBILE_MARGIN, TWENTY_PX,
)
from css_rules import declaration, find_rules_with_selector, parse_rules

ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT / "static"


def test_desktop_fixed_rule_unchanged():
    css = (STATIC_DIR / "chat-feedback.css").read_text(encoding="utf-8")
    base = [rule for rule in find_rules_with_selector(parse_rules(css), ".feedback-notice")
            if rule.media is None]
    assert len(base) == 1
    assert declaration(base[0], POSITION) == FIXED
    assert declaration(base[0], RIGHT) == TWENTY_PX
    assert declaration(base[0], TOP) == TWENTY_PX


def test_mobile_rule_takes_flow_space():
    css = (STATIC_DIR / "chat-feedback.css").read_text(encoding="utf-8")
    mobile = [rule for rule in find_rules_with_selector(parse_rules(css), ".feedback-notice")
              if rule.media == "(max-width: 920px)"]
    assert len(mobile) == 1
    assert declaration(mobile[0], POSITION) == STATIC
    assert declaration(mobile[0], MARGIN) == MOBILE_MARGIN
    assert declaration(mobile[0], MAX_WIDTH) == NONE
    # 고정 배치의 덮기 좌표를 다시 선언하지 않는다.
    assert declaration(mobile[0], TOP) is None
    assert declaration(mobile[0], RIGHT) is None


def test_notice_sits_between_topbar_and_screen_sections():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    topbar_open = html.index('<header class="topbar">')
    header_end = html.index("</header>", topbar_open)
    notice = html.index('<aside class="feedback-notice" id="feedbackNotice"')
    first_section = html.index('<section class="', notice)
    assert topbar_open < header_end < notice < first_section
    tag = re.search(r'<aside class="feedback-notice"[^>]*>', html).group()
    assert HIDDEN in tag
    assert ROLE_STATUS in tag
    assert ARIA_LIVE in tag
    # 숨김 규칙 유지 — 알림이 없으면 자리를 차지하지 않는다.
    css = (STATIC_DIR / "chat-feedback.css").read_text(encoding="utf-8")
    assert HIDDEN_RULE in css
