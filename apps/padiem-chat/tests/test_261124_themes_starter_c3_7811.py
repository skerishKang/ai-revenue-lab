"""Style contract for #7811 C3 — the starter-card overrides in ``padiem-themes.css``.

Second pass over ``padiem-themes.css`` (the composer was the first). It covers
the starter cards (``.starter``, its ``strong`` / ``small`` and
``.starter-icon``): 43 themed declarations before, 25 after.

* 18 declarations never painted in the shipped cascade — a later rule of the
  same sheet, a later sheet with a longer selector or an ``!important`` always
  won, or the declaration only repeated what the base rule already computes to.
  They are gone, and each removal is pinned here to the rule that paints
  instead, so removing that owner later fails loudly rather than silently
  changing the cards.
* Nothing moved into a theme token value this time, and ``padiem-tokens.css``
  is untouched. The one candidate — the icon border in ``light`` and
  ``padiem-home``, whose base rule reads ``--surfaces-starter-icon-border``
  and nothing else does — is blocked by the base rule's second selector:
  ``.starter:nth-child(2n) .starter-icon`` (0,3,0) outranks the theme rule
  (0,2,1), so today the even cards' icons keep the ``:root`` border and only
  the odd cards' icons take the theme one. A theme value on the token would
  repaint the even cards' icons.

The 25 that remain still beat a base rule whose shape a theme token cannot
express yet (a flat or 180° surface against a 145° two-layer gradient, a
different shadow stack, a blur literal, a border shorthand, a token another
component also reads), are outranked on part of the cards (the icon border
above), or carry a state the base rule does not cover (the light hover rule
also applies to a disabled card). The exact remainder is pinned so a re-added
override or a new ``!important`` shows up as a diff here.

Sheet reads go through ``_support/theme_sheets.py`` (the structure audit
tool's parser); this module asserts on parsed rules and token values only.
"""
from __future__ import annotations

import re

from _support import theme_sheets as sheets

THEME_SHEET = "padiem-themes.css"
STARTER_RX = re.compile(r"\.starter(-icon)?\b")
THEMES = ("light", "dark", "cinematic", "padiem-home", "padiem-glass")
ICON_BORDER = "--surfaces-starter-icon-border"

#: Every starter declaration the theme sheet still carries: selector → {prop: value}.
REMAINING = {
    'html[data-theme="light"] .starter': {
        "border": "1px solid var(--line)",
        "color": "var(--text)",
        "backdrop-filter": "none",
        "background": "linear-gradient(180deg, #ffffff 0%, #fcfcfe 100%)",
        "border-color": "#e6e6eb",
        "box-shadow": "0 2px 10px rgba(101,87,232,.05), 0 1px 3px rgba(30,28,54,.04)",
    },
    'html[data-theme="light"] .starter:hover': {
        "border-color": "rgba(101,87,232,.16)",
        "box-shadow": "0 4px 16px rgba(101,87,232,.09)",
    },
    'html[data-theme="light"] .starter-icon': {
        "color": "#6b6b7a",
        "background": "linear-gradient(180deg, #f3f2f8, #eceaf6)",
        "border": "1px solid rgba(101,87,232,.10)",
    },
    'html[data-theme="dark"] .starter': {
        "background": "var(--card-bg)",
        "box-shadow": "none",
        "backdrop-filter": "none",
    },
    'html[data-theme="dark"] .starter:not(:disabled):hover': {
        "border-color": "rgba(255,255,255,.18)",
        "box-shadow": "0 2px 8px rgba(0,0,0,.20)",
    },
    'html[data-theme="padiem-home"] .starter': {
        "background": "linear-gradient(180deg, rgba(255,255,255,.82), rgba(250,252,255,.68))",
        "border": "1px solid rgba(26,34,48,.08)",
        "border-top": "1px solid rgba(255,255,255,.85)",
        "color": "var(--text-deep-ink)",
        "box-shadow": "0 10px 28px rgba(26,34,48,.07), inset 0 1px 0 rgba(255,255,255,.8)",
        "backdrop-filter": "blur(16px)",
    },
    'html[data-theme="padiem-home"] .starter-icon': {
        "background": "rgba(26,34,48,.06)",
        "border": "1px solid rgba(26,34,48,.08)",
        "color": "#3a4a62",
    },
}



def _norm(text: str) -> str:
    return " ".join(text.split())


def _selectors(rule) -> list[str]:
    """One parsed rule's selector list, split on top-level commas."""
    parts, depth, current = [], 0, ""
    for char in rule.selector:
        if char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        if char == "," and depth == 0:
            parts.append(_norm(current))
            current = ""
        else:
            current += char
    parts.append(_norm(current))
    return parts


def _declared(sheet_name: str, selector: str) -> dict[str, str]:
    """prop → value over every top-level rule of ``sheet_name`` listing ``selector`` exactly."""
    found: dict[str, str] = {}
    for rule in sheets.rules(sheet_name):
        if selector in _selectors(rule):
            for prop, value in sheets.decl_map(rule).items():
                found[prop] = _norm(value)
    return found


def _root_value(prop: str) -> str | None:
    """The value the ``:root`` block of padiem-tokens.css gives ``prop``."""
    for rule in sheets.rules("padiem-tokens.css"):
        if ":root" in _selectors(rule) and prop in sheets.decl_map(rule):
            return _norm(sheets.decl_map(rule)[prop])
    return None


def _theme_sheet_starter() -> dict[str, dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    for rule in sheets.rules(THEME_SHEET):
        if not STARTER_RX.search(rule.selector):
            continue
        assert len(_selectors(rule)) == 1, rule.selector
        found.setdefault(_norm(rule.selector), {}).update(
            {prop: _norm(value) for prop, value in sheets.decl_map(rule).items()})
    return found


def test_the_theme_sheet_keeps_exactly_the_blocked_starter_overrides():
    assert _theme_sheet_starter() == REMAINING
    assert sum(len(declarations) for declarations in REMAINING.values()) == 25


def test_no_starter_override_is_important():
    flagged = [
        (selector, prop)
        for selector, declarations in _theme_sheet_starter().items()
        for prop, value in declarations.items()
        if "!important" in value
    ]
    assert flagged == []


def test_the_icon_border_stays_in_the_theme_sheet_while_the_even_card_selector_outranks_it():
    # The base icon rule lists two selectors. The second one, (0,3,0), outranks
    # the theme sheet's icon rule, (0,2,1): even cards' icons keep the :root
    # border value, odd cards' icons take the theme rule's. A theme value on
    # the token would reach both, so no theme block may give the token a value
    # while that selector is there.
    readers = set()
    for sheet_name in sheets.shipped_sheet_names():
        if sheet_name == "padiem-tokens.css":
            continue
        for rule in sheets.rules(sheet_name):
            for prop, value in sheets.decl_map(rule).items():
                if f"var({ICON_BORDER})" in value:
                    assert _norm(value) == f"1px solid var({ICON_BORDER})"
                    for selector in _selectors(rule):
                        readers.add((sheet_name, selector, prop))
    assert readers == {
        ("padiem-surfaces.css", ".starter-icon", "border"),
        ("padiem-surfaces.css", ".starter:nth-child(2n) .starter-icon", "border"),
    }
    for theme in THEMES:
        assert sheets.token_value(theme, ICON_BORDER) is None, theme


def test_the_cinematic_card_is_painted_by_the_readability_sheet_and_the_base_rule():
    # No cinematic starter rule is left in the theme sheet.
    assert [selector for selector in _theme_sheet_starter() if "cinematic" in selector] == []
    # Surface, edge and glow: the readability rule keeps the values but carries
    # no flag since the 261127 decision (the phone-width Claw strip rule in
    # connector-pages.css wins on specificity now, like in the other themes).
    box = _declared("padiem-bright-readability.css", 'html[data-theme="cinematic"] .starter')
    for prop in ("background", "border-color", "box-shadow"):
        assert prop in box, prop
        assert "!important" not in box[prop], prop
    # Text colour and blur: the removed values repeated the base rule's own.
    base = _declared("padiem-surfaces.css", ".starter")
    assert base["color"] == "var(--surfaces-starter-text)"
    assert base["backdrop-filter"] == "blur(18px)"
    assert sheets.token_value("cinematic", "--surfaces-starter-text") is None
    assert _root_value("--surfaces-starter-text") == "rgba(248, 250, 253, .94)"


def test_the_card_title_colour_comes_from_the_base_rule_token():
    # The removed title overrides (light: var(--text), padiem-home: the deep
    # ink that equals its --text) repeated what the base rule computes to.
    assert _declared("padiem-surfaces.css", ".starter strong")["color"] == "var(--panel-text-max)"
    for theme in ("light", "padiem-home"):
        assert sheets.token_value(theme, "--panel-text-max") == "var(--text)", theme
        assert _declared(THEME_SHEET, f'html[data-theme="{theme}"] .starter strong') == {}, theme
    assert sheets.token_value("padiem-home", "--text") == "#1a2230"
    assert _root_value("--text-deep-ink") == "#1a2230"


def test_the_card_caption_colour_is_painted_by_the_accessibility_sheet():
    # Same selector, same specificity, later sheet, flagged.
    expected = {"light": "#565e69 !important", "padiem-home": "#4e5968 !important"}
    for theme, colour in expected.items():
        selector = f'html[data-theme="{theme}"] .starter small'
        assert _declared("accessibility-polish.css", selector)["color"] == colour, theme
        assert _declared(THEME_SHEET, selector) == {}, theme


def test_the_dark_card_edge_and_text_are_painted_by_the_dark_contrast_sheet():
    group = [
        rule for rule in sheets.rules_with_selector("padiem-dark-contrast.css", ".starter")
        if 'html[data-theme="dark"] body .app-shell :is(' in _norm(rule.selector)
    ]
    assert len(group) == 1
    declared = {prop: _norm(value) for prop, value in sheets.decl_map(group[0]).items()}
    assert declared["border-color"] == "#435d72"
    assert declared["color"] == "#edf6fe"
    dark = REMAINING['html[data-theme="dark"] .starter']
    assert "border-color" not in dark and "color" not in dark


def test_the_light_card_surface_and_icon_keep_one_declaration_each():
    # The sheet used to set the light surface, shadow and icon background twice;
    # the earlier of each pair never painted. One declaration of each is left.
    counts: dict[tuple[str, str], int] = {}
    for rule in sheets.rules(THEME_SHEET):
        selector = _norm(rule.selector)
        if selector in ('html[data-theme="light"] .starter', 'html[data-theme="light"] .starter-icon'):
            for prop in sheets.decl_map(rule):
                counts[(selector, prop)] = counts.get((selector, prop), 0) + 1
    assert set(counts.values()) == {1}
