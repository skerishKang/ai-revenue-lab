"""#5908 — the quick-run toolbox cards over the EXISTING panels and flows.

The owner-approved scope: six cards (축사·인사말 / SNS 홍보 / 회의정리·활동집 /
PDF → Markdown / 견적서 초안 / Excel 열기·검토) inside the existing util view.
The four util cards reuse the same ``activateUtilTab`` switch the sidebar
submenu drives; the two Claw cards route to the existing Claw workspace and
its own chip handler. No second engine, no new routes.

The flow-linked cards must say so in their buttons ("Claw에서 …") — they are
not direct-run claims. The PDF → Markdown card must carry the truthful paused
note (COM2 migration; existing history/download still work).

Static assertions pin the markup/CSS contracts; the Node harness executes the
REAL util-menu.js against the same fake-DOM host the #5608/#5785 suites use
and proves the actual routing.
"""

from __future__ import annotations

import re
from pathlib import Path

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
    # The two flow-linked cards name their destination instead of pretending
    # to execute here; the three direct util cards keep the plain 열기 wording.
    assert _card_button_label("claw-quote") == "Claw에서 작성"
    assert _card_button_label("claw-excel") == "Claw에서 진행"
    assert _card_button_label("speech") == "열기"
    assert _card_button_label("sns") == "열기"
    assert _card_button_label("meeting") == "열기"


def test_pdfmd_card_carries_the_truthful_paused_note() -> None:
    grid = _grid()
    pdfmd = grid[grid.index("util-tool-paused") : grid.index('data-util-tool="claw-quote"')]
    assert "PDF → Markdown" in pdfmd
    assert "util-tool-note" in pdfmd
    assert "일시 중단" in pdfmd
    assert "새 업로드는 잠시 멈춤" in pdfmd
    # The note stays truthful without naming the deployment: the internal host
    # name is not screen copy, and the move it referred to finished 2026-10-31.
    assert "COM2" not in pdfmd
    assert _card_button_label("pdfmd") == "이력 열기"


# ── behaviour contract in util-menu.js ──────────────────────────────────────


def test_util_menu_routes_cards_through_the_existing_switch() -> None:
    js = UTIL_MENU_JS.read_text(encoding="utf-8")
    assert 'document.getElementById("utilToolGrid")' in js
    assert 'querySelectorAll("[data-util-tool]")' in js
    # The util cards reuse activateUtilTab; the sidebar highlight keeps its
    # single owner (markActiveUtilSubmenuItem), exactly like the submenu rows.
    assert "activateUtilTab(tab);" in js
    assert "markActiveUtilSubmenuItem(key);" in js
    # The Claw cards go through the existing Claw nav button and the existing
    # quote chip — no duplicated Claw state inside util-menu.js.
    assert 'document.getElementById("clawNavButton")' in js
    assert 'document.getElementById("clawQuoteCard")' in js


# ── CSS contract ────────────────────────────────────────────────────────────


def test_css_uses_the_measured_contrast_token_and_44px_touch_target() -> None:
    css = UTIL_MENU_CSS.read_text(encoding="utf-8")
    assert ".util-tool-grid" in css
    # #6317: --input-border-strong renders 6.33:1 on glass; --line is the
    # 1.03:1 token that report flagged on the .pdfmd-* controls.
    card = css[css.index(".util-tool-card {") : css.index(".util-tool-card {") + 400]
    assert "--input-border-strong" in card
    button = css[css.index(".util-tool-open {") : css.index(".util-tool-open:hover")]
    assert "min-height: 44px" in button
    # The glass CTA colour keeps the shared composer rule: the toolbox button
    # is listed with .pdfmd-btn-primary, not a new colour.
    glass = css[css.index('html[data-theme="padiem-glass"] .util-tool-open') :]
    glass_block = glass[: glass.index("}") + 1]
    assert ".pdfmd-btn-primary" in glass_block
    assert "#355977" in glass_block
