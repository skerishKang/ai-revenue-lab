"""#7173 — the util tool screens keep the #7172 design contract.

Static, stylesheet-level only: the primary buttons that the tool screens add
join the app-wide navy rule in all three state blocks, at the same list
position; the new chrome (back control, notice) uses the shared tokens. What a
browser paints is measured in browser_util_inapp_screens_7173.py and in the
screenshots attached to the PR, not here.
"""

from __future__ import annotations

from pathlib import Path

import css_rules
from css_rules import (
    declaration,
    find_rules_with_selector,
    is_list_items,
    parse_rules,
)

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
INDEX_HTML = (STATIC / "index.html").read_text(encoding="utf-8")
UTIL_CSS = (STATIC / "util-menu.css").read_text(encoding="utf-8")
POLISH_CSS = (STATIC / "padiem-chat-ui-polish.css").read_text(encoding="utf-8")
UTIL_JS = (STATIC / "util-menu.js").read_text(encoding="utf-8")


def _shared_primary_blocks():
    rules = parse_rules(POLISH_CSS)
    blocks = [
        rule for rule in rules
        if is_list_items(rule.selectors[0]) and ".util-tool-open" in is_list_items(rule.selectors[0])
    ]
    assert len(blocks) == 3, [rule.selectors for rule in blocks]
    return blocks


def test_every_new_primary_button_rides_the_shared_navy_rule() -> None:
    base, hover, focus = _shared_primary_blocks()
    # Same list position in every state block, like the #7172 card buttons.
    assert is_list_items(base.selectors[0]) == is_list_items(hover.selectors[0])
    assert is_list_items(base.selectors[0]) == is_list_items(focus.selectors[0])
    members = is_list_items(base.selectors[0])
    assert ".util-generate" in members
    # The values themselves stay the app-wide ones; no second palette.
    assert declaration(base, "background") == "#355977"
    assert declaration(base, "border-color") == "#294b64"
    assert declaration(base, "color") == "#fff"
    assert declaration(hover, "background") == "#2e4d67"
    assert declaration(focus, "outline") == "3px solid #6a9abc"


def test_the_back_control_is_a_44px_pill_on_the_shared_tokens() -> None:
    rules = find_rules_with_selector(parse_rules(UTIL_CSS), ".util-back")
    base = [rule for rule in rules if rule.media is None]
    assert len(base) == 1
    assert declaration(base[0], "min-height") == "44px"
    assert declaration(base[0], "border-radius") == "999px"
    assert declaration(base[0], "border").startswith("1px solid var(--line")


def test_the_first_screen_and_the_screens_share_one_page() -> None:
    # The card grid and every tool panel live in the same util view; the panel
    # is what changes, not the page.
    section = INDEX_HTML[INDEX_HTML.index('id="utilView"'):INDEX_HTML.index('id="calendarView"')]
    assert 'id="utilToolGrid"' in section
    for card in ("speech", "sns", "meeting", "pdfmd", "claw-quote", "claw-excel"):
        assert f'data-util-tool="{card}"' in section, card
    assert 'id="utilToolNotice"' in section


def test_the_excel_card_says_it_opens_a_new_tab() -> None:
    # The one tool Chat cannot host is stated in the card, not discovered after
    # a click.
    section = INDEX_HTML[INDEX_HTML.index('id="utilView"'):INDEX_HTML.index('id="calendarView"')]
    excel = section[section.index('data-util-tool="claw-excel"') - 400:section.index('data-util-tool="claw-excel"')]
    assert "새 탭에서 열기" in section
    assert "Excel" in excel


def test_a_screen_writes_its_own_route_and_never_leaves() -> None:
    assert 'const UTIL_HOME_HASH = "#util";' in UTIL_JS
    assert 'UTIL_HOME_HASH + "/" + key' in UTIL_JS
    assert "history.replaceState" in UTIL_JS
    assert "window.open" in UTIL_JS  # the one documented new-tab exception
    assert UTIL_JS.count("window.open") == 1
