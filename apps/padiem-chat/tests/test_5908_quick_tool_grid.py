"""#5908 — the quick-run toolbox cards over the EXISTING panels and flows.

The owner-approved scope: six cards (축사·인사말 / SNS 홍보 / 회의정리·활동집 /
PDF → Markdown / 견적서 초안 / Excel 열기·검토) inside the existing util view.
#7173: every card opens its tool's screen inside this page through the one
``openUtilScreen`` switch, and the authoring screens reuse the existing
contracts. The single card Chat cannot host is Excel review, whose reader is
the Claw conversation; it says «새 탭에서 열기» and opens a new tab instead of
moving the page.

The PDF → Markdown card describes the open conversion surface; its only pause
sentence is the one the panel shows when the server actually answers that new
work is blocked (#5710 gate).

Static assertions pin the markup/CSS contracts. The executed routing (screen
opens, ← 유틸 returns, no navigation) is browser-level in
browser_util_inapp_screens_7173.py.
"""

from __future__ import annotations

import re
from pathlib import Path

from css_rules import (
    declaration,
    find_rules_with_selector,
    parse_rules,
    rule_selector_list_contains,
    strip_comments,
)

ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "static/index.html"
UTIL_MENU_JS = ROOT / "static/util-menu.js"
UTIL_MENU_CSS = ROOT / "static/util-menu.css"

TOOL_KEYS = ("speech", "sns", "meeting", "pdfmd", "claw-quote", "claw-excel")


def _html() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def _grid() -> str:
    html = _html()
    return html[html.index('id="utilToolGrid"') : html.index('id="calendarView"')]


def _card_button_label(key: str) -> str:
    match = re.search(
        r'<button[^>]*data-util-tool="' + key + r'"[^>]*>([^<]*)</button>', _grid()
    )
    assert match, f"missing tool card button: {key}"
    return match.group(1).strip()


# ── markup contract ─────────────────────────────────────────────────────────


def test_grid_sits_inside_the_util_view_with_six_cards() -> None:
    grid = _grid()
    assert 'aria-label="빠른 실행 도구함"' in grid
    assert grid.count("util-tool-card") == 6
    for key in TOOL_KEYS:
        assert f'data-util-tool="{key}"' in grid, f"missing tool card: {key}"


def test_flow_linked_cards_do_not_claim_direct_run() -> None:
    # #7173: the quote card now runs in this page (its own screen), so it says
    # what it opens instead of naming another product. Excel review is the one
    # surface Chat cannot host, and its button names that destination.
    assert _card_button_label("claw-quote") == "초안 열기"
    assert _card_button_label("claw-excel") == "새 탭에서 열기"
    assert _card_button_label("speech") == "열기"
    assert _card_button_label("sns") == "열기"
    assert _card_button_label("meeting") == "열기"


def test_pdfmd_card_describes_open_conversion() -> None:
    """#5710's static paused note is gone: new work is enabled, and the only
    pause sentence left is the one the panel itself shows when the server
    actually answers that new work is blocked."""
    grid = _grid()
    pdfmd = grid[grid.index('data-util-tool="meeting"') : grid.index('data-util-tool="claw-quote"')]
    assert "PDF → Markdown" in pdfmd
    assert "util-tool-paused" not in pdfmd
    assert "util-tool-note" not in pdfmd
    assert "일시 중단" not in pdfmd
    assert "새 업로드는 잠시 멈춤" not in pdfmd
    assert "PDF·ZIP을 Markdown으로 변환·비교·다운로드" in pdfmd
    assert _card_button_label("pdfmd") == "열기"


def test_pdfmd_tab_tagline_matches_the_card_copy() -> None:
    html = _html()
    tagline = 'data-tagline="PDF·ZIP을 Markdown으로 변환·비교·다운로드"'
    assert tagline in html
    # 대표 결정 #7172로 계약 값 갱신: the first screen heading is '유틸', so the
    # page tagline is the util collection copy. The PDF copy stays on its tab
    # (data-tagline above) and on the card, not on the page heading.
    assert 'id="utilTagline" data-locale-key="util-tagline">자주 쓰는 문서·홍보 도구 모음</p>' in html
    assert 'id="utilTagline">PDF·ZIP을 Markdown으로 변환·비교·다운로드</p>' not in html
    assert "기존 작업 이력·결과 다운로드" not in html


# ── behaviour contract in util-menu.js ──────────────────────────────────────


def test_util_menu_routes_cards_through_the_existing_switch() -> None:
    js = UTIL_MENU_JS.read_text(encoding="utf-8")
    assert 'document.getElementById("utilToolGrid")' in js
    assert 'querySelectorAll("[data-util-tool]")' in js
    # #7173: the cards reuse the one openUtilScreen switch; the sidebar
    # highlight keeps its single owner (markActiveUtilSubmenuItem), exactly
    # like the submenu rows.
    assert "function openUtilScreen(key)" in js
    assert "openUtilScreen(key === \"claw-quote\" ? \"quote\" : key)" in js
    assert "markActiveUtilSubmenuItem(key === \"quote\"" in js
    # The quote result's one Claw bridge uses the existing nav button and
    # chip — no duplicated Claw state inside util-menu.js.
    assert 'document.getElementById("clawNavButton")' in js
    assert 'document.getElementById("clawQuoteCard")' in js


# ── CSS contract ────────────────────────────────────────────────────────────


def test_css_uses_the_measured_contrast_token_and_44px_touch_target() -> None:
    """The card border and the button's size/colour are rule-level contracts.

    #7186: read through css_rules, so a re-wrapped or re-ordered block keeps
    the same verdict (tests/test_css_rules_helper.py proves the helper).
    """
    css = UTIL_MENU_CSS.read_text(encoding="utf-8")
    assert ".util-tool-grid" in css
    rules = parse_rules(css)
    # 대표 결정 #7172로 계약 값 갱신: the first-screen card border is the shared
    # hairline token (var(--line)), not the input-strength token. The contrast
    # floor itself is unchanged and still proven in test_beta_ux_quote_access.
    cards = find_rules_with_selector(rules, ".util-tool-card")
    assert len(cards) == 1
    border = declaration(cards[0], "border")
    assert border.startswith("1px solid var(--line"), border
    assert [v for v in cards[0].declarations.values() if "input-border-strong" in v] == []
    buttons = find_rules_with_selector(rules, ".util-tool-open")
    assert len(buttons) == 1
    assert declaration(buttons[0], "min-height") == "44px"
    # 대표 결정 #7172로 계약 값 갱신: the glass-only CTA override is superseded
    # by the app-wide shared primary rule; the toolbox button still wears the
    # same #355977 as .pdfmd-btn-primary.
    assert 'html[data-theme="padiem-glass"] .util-tool-open' not in strip_comments(css)
    polish = parse_rules((ROOT / "static/padiem-chat-ui-polish.css").read_text(encoding="utf-8"))
    blocks = find_rules_with_selector(polish, ".util-tool-open")
    assert len(blocks) == 3
    for block in blocks:
        assert rule_selector_list_contains(block, ".util-tool-open", ".pdfmd-btn-primary")
    navy = [block for block in blocks if declaration(block, "background") == "#355977"]
    assert len(navy) == 1
