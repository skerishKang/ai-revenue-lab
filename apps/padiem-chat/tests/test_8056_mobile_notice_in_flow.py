"""#8056 — 모바일(≤600px)에서 고침 알림이 흐름 안에서 자리를 차지한다.

390 폭 홈에서 .feedback-notice 의 고정 배치 규칙이 '안녕하세요. 무엇을
도와드릴까요?' 인사말 제목을 덧대는 결함(#8056)을 잡는다. 계약 3가지:

1. 데스크톱 규칙은 그대로다 — base .feedback-notice 는 position:fixed 유지
   (1440 우측 위 띄움은 바뀌지 않는다).
2. (max-width: 600px) 범위에서는 position:static 으로 흐름에 들어와 자리를
   차지하고, 고정 배치의 덮기 좌표(top·right)를 다시 선언하지 않는다.
3. aside#feedbackNotice 는 상단 topbar 다음, 화면 섹션들 앞에 놓여 흐름
   배치가 인사말 위에서 시작되도록 한다. hidden 일 때는 자리를 차지하지 않는다.
"""
from __future__ import annotations

import re
from pathlib import Path

from css_rules import declaration, find_rules_with_selector, parse_rules

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"


def test_desktop_fixed_rule_unchanged():
    css = (STATIC / "chat-feedback.css").read_text(encoding="utf-8")
    base = [rule for rule in find_rules_with_selector(parse_rules(css), ".feedback-notice")
            if rule.media is None]
    assert len(base) == 1
    assert declaration(base[0], "position") == "fixed"
    assert declaration(base[0], "right") == "20px"
    assert declaration(base[0], "top") == "20px"


def test_mobile_rule_takes_flow_space():
    css = (STATIC / "chat-feedback.css").read_text(encoding="utf-8")
    mobile = [rule for rule in find_rules_with_selector(parse_rules(css), ".feedback-notice")
              if rule.media == "(max-width: 600px)"]
    assert len(mobile) == 1
    assert declaration(mobile[0], "position") == "static"
    assert declaration(mobile[0], "margin") == "12px"
    assert declaration(mobile[0], "max-width") == "none"
    # 고정 배치의 덮기 좌표를 다시 선언하지 않는다.
    assert declaration(mobile[0], "top") is None
    assert declaration(mobile[0], "right") is None


def test_notice_sits_between_topbar_and_screen_sections():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    topbar_open = html.index('<header class="topbar">')
    header_end = html.index("</header>", topbar_open)
    notice = html.index('<aside class="feedback-notice" id="feedbackNotice"')
    first_section = html.index('<section class="', notice)
    assert topbar_open < header_end < notice < first_section
    tag = re.search(r'<aside class="feedback-notice"[^>]*>', html).group()
    assert "hidden" in tag
    assert 'role="status"' in tag
    assert 'aria-live="polite"' in tag
    # 숨김 규칙 유지 — 알림이 없으면 자리를 차지하지 않는다.
    css = (STATIC / "chat-feedback.css").read_text(encoding="utf-8")
    assert ".feedback-notice[hidden] { display: none !important; }" in css
