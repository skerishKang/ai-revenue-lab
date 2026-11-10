"""#7172 (갱신 #7173) — 유틸 첫 화면 계약.

- 제목·설명은 '유틸'(ko/en) — 도구 하나의 이름(PDF → Markdown)이 아니라.
- 카드는 **전체가 눌리는 단추**이고(11-10 결정), 별도 열기·이력·Claw 버튼이 없다.
- 카드 테두리는 첫 화면 카드와 같은 옅은 토큰(var(--line)).
- 다시 들어오면 제목이 '유틸'로 돌아온다(util-app.js가 그린다).
"""
from pathlib import Path

from css_rules import declaration, find_rules_with_selector, parse_rules

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
LOCALE = (STATIC / "locale.js").read_text(encoding="utf-8")
UTIL_APP_CSS = (STATIC / "util-app.css").read_text(encoding="utf-8")
UTIL_APP_JS = (STATIC / "util-app.js").read_text(encoding="utf-8")


def test_first_screen_heading_is_the_util_page_itself() -> None:
    start = INDEX.index('id="utilTitle"')
    heading = INDEX[max(0, start - 200):start + 300]
    assert 'data-locale-key="util-title"' in heading
    assert '>유틸</h2>' in heading
    assert 'data-locale-key="util-tagline"' in heading
    assert "자주 쓰는 문서·홍보 도구 모음" in heading
    # The PDF tool name is a CARD below, never the page heading.
    title_line = INDEX[INDEX.index('id="utilTitle"'):INDEX.index('id="utilTagline"')]
    assert "PDF → Markdown" not in title_line


def test_util_title_keys_exist_in_both_languages() -> None:
    assert '"util-title": "유틸"' in LOCALE
    assert '"util-tagline": "자주 쓰는 문서·홍보 도구 모음"' in LOCALE
    assert '"util-title": "Util"' in LOCALE
    assert '"util-tagline": "Everyday document & promo tools"' in LOCALE
    assert '"app-switch-label": "앱 전환"' in LOCALE
    assert '"app-switch-label": "Switch app"' in LOCALE


def test_whole_card_button_wears_the_hairline_token_and_shared_focus() -> None:
    rules = parse_rules(UTIL_APP_CSS)
    cards = find_rules_with_selector(rules, ".util-card")
    assert cards, "the util card rule is missing"
    border = next((declaration(rule, "border") for rule in cards if declaration(rule, "border")), "")
    assert border.startswith("1px solid var(--line"), border
    assert [value for rule in cards for value in rule.declarations.values()
            if "input-border-strong" in value] == []
    assert '<button type="button" class="util-card"' in UTIL_APP_JS
    for gone in ("util-tool-open", "이력 열기", "Claw에서"):
        assert gone not in UTIL_APP_JS, gone


def test_reopening_the_page_resets_the_heading() -> None:
    # util-app.js paints the first-screen heading on every list render; the
    # tool's own name belongs to the tool screen (h3 + back link).
    assert "function setUtilHeading" in UTIL_APP_JS
    section = UTIL_APP_JS[UTIL_APP_JS.index("function setUtilHeading"):UTIL_APP_JS.index("function syncTabs")]
    assert '"Util"' in section
    assert "자주 쓰는 문서·홍보 도구 모음" in section
    assert "util-tool-heading" in UTIL_APP_JS
