"""#7476 H1–H5: the advanced-settings page is one of the standalone pages.

The page used to keep its own header row (kicker, title and back pill as three
siblings), its own copy of the Glass plate in standalone-views.css, and the
dialog's section padding. This contract pins the shared membership instead:
the common header rules name ``settings``, the plate and the phone scroll live
where the other pages get them, the back entry is a header chip, and the PC
blocks start on one line.
"""

from __future__ import annotations

from pathlib import Path

from css_rules import (
    declaration,
    parse_rules,
    rule_selector_list_contains,
)

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
VIEWS_CSS = (STATIC / "standalone-views.css").read_text(encoding="utf-8")
FRAME_CSS = (STATIC / "shared-six-panel-frame.css").read_text(encoding="utf-8")
POLISH_CSS = (STATIC / "padiem-chat-ui-polish.css").read_text(encoding="utf-8")
SETTINGS_CSS = (STATIC / "padiem-settings.css").read_text(encoding="utf-8")  # #7476-14


def _rules(css: str):
    return parse_rules(css)


def _with_all(rules, *selectors):
    return [rule for rule in rules if rule_selector_list_contains(rule, *selectors)]


def _selector_text(rule) -> str:
    return " ".join(rule.selectors)


def _rule_mentioning(rules, text: str):
    found = [rule for rule in rules if text in _selector_text(rule)]
    assert found, f"no rule mentions {text!r}"
    return found


def test_the_kicker_and_title_are_one_header_column() -> None:
    start = HTML.index('id="advancedSettingsView"')
    header = HTML[start : HTML.index("</header>", start)]
    assert 'class="standalone-view-header"' in header
    assert header.index("<div>") < header.index('data-locale-key="settings-kicker"')
    assert header.index("<div>") < header.index('id="advancedSettingsTitle"')
    # The back entry is the header's second child, outside the title column.
    assert header.index("</div>") < header.index('id="advancedSettingsBack"')


def test_settings_joins_the_shared_title_kicker_and_stack_rules() -> None:
    rules = _rules(VIEWS_CSS)
    title_rules = [rule for rule in _rule_mentioning(rules, ".standalone-view-title") 
                   if declaration(rule, "font-weight") == "770"]
    assert title_rules, "shared standalone title rule not found"
    assert any('[data-state="settings"]' in _selector_text(rule) for rule in title_rules)
    assert "clamp(26px, 4vw, 34px)" == declaration(title_rules[0], "font-size")

    kicker_rules = [rule for rule in _rule_mentioning(rules, ".calendar-view-kicker")
                    if declaration(rule, "letter-spacing") == ".13em"]
    assert kicker_rules, "shared kicker rule not found"
    assert any('[data-state="settings"]' in _selector_text(rule) for rule in kicker_rules)

    stack_rules = _rule_mentioning(rules, ".util-header > div")
    assert any('[data-state="settings"]' in _selector_text(rule) for rule in stack_rules)

    header_rules = [rule for rule in _rule_mentioning(rules, ".standalone-view-header")
                    if declaration(rule, "min-height") == "44px"]
    assert header_rules, "shared header geometry rule not found"
    assert any('[data-state="settings"]' in _selector_text(rule) for rule in header_rules)


def test_settings_plate_is_member_of_every_shared_frame_lane() -> None:
    rules = _rules(FRAME_CSS)
    lanes = [rule for rule in rules if ".settings-advanced-view" in _selector_text(rule)]
    # plate, ultrawide margin, padding origin, collapsed sidebar, content height
    assert len(lanes) >= 5, [rule.selectors for rule in lanes]
    for rule in lanes:
        assert ".connectors-view" in _selector_text(rule), rule.selectors

    plate = [
        rule for rule in lanes
        if declaration(rule, "width") == "var(--padiem-six-panel-width) !important"
    ]
    assert plate, "the six-panel plate literal must be the shared one"
    padding = [
        rule for rule in lanes
        if declaration(rule, "padding") == (
            "calc(var(--padiem-first-screen-inset) - 7px) var(--padiem-six-panel-pad-x) 36px !important"
        )
    ]
    assert padding, "the shared first-screen origin must name settings"

    relaxed = [rule for rule in lanes if declaration(rule, "height") == "auto !important"]
    assert relaxed, "settings and connectors must size to their content"
    assert declaration(relaxed[0], "max-height") == "var(--padiem-six-panel-height) !important"


def test_the_back_entry_is_a_header_secondary_chip() -> None:
    rules = _rules(VIEWS_CSS)
    back = _rule_mentioning(rules, "#advancedSettingsBack")
    assert declaration(back[0], "min-height") == "44px"
    assert declaration(back[0], "border-radius") == "10px"
    assert declaration(back[0], "background") == "var(--card-bg, #fafafa)"


def test_pc_blocks_share_one_left_edge_and_reading_size() -> None:
    # #7476-14: some settings rules now live in the consolidated sheet.
    rules = _rules(POLISH_CSS) + _rules(SETTINGS_CSS)
    section = _rule_mentioning(rules, ".settings-advanced-view .settings-section")
    assert any(declaration(rule, "padding") == "0" for rule in section)
    copy = _rule_mentioning(rules, ".pc-delegation-settings > p")
    assert any(declaration(rule, "font-size") == "14px" for rule in copy)
    assert any(":not(.settings-label)" in _selector_text(rule) for rule in copy)

    selected = _with_all(rules, ".settings-advanced-view .advanced-menu-link.selected")
    assert selected, "selected menu rule not found"
    assert declaration(selected[0], "color") == "var(--accent-strong)"
    assert declaration(selected[0], "font-weight") == "750"


def test_the_phone_page_scrolls_inside_the_panel_like_connectors() -> None:
    rules = _rules(VIEWS_CSS)
    scroller = [
        rule for rule in rules
        if ".settings-advanced-view" in _selector_text(rule)
        and declaration(rule, "max-height") == "calc(100dvh - 62px)"
    ]
    assert scroller, "the phone scroll cap must mirror the connectors page"
    assert declaration(scroller[0], "overflow-y") == "auto"


def test_the_old_copied_plate_is_gone_from_the_view_sheet() -> None:
    assert ".settings-advanced-view" in VIEWS_CSS  # state gating + phone plate
    assert "var(--padiem-six-panel-width)" not in VIEWS_CSS
    assert "border-radius: 30px" in VIEWS_CSS  # only the <=920 plate remains
