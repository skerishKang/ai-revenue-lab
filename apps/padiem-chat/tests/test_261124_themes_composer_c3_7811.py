"""Style contract for #7811 C3 — the composer overrides in ``padiem-themes.css``.

C3 takes the theme override sheets apart one component at a time. This is the
first pass over ``padiem-themes.css`` and covers the composer (``.composer``,
``.composer-wrap``, ``.composer-note`` and the composer textarea): 46 themed
declarations before, 17 after, and none of them ``!important`` any more.

* 17 declarations never painted in the shipped cascade — a later sheet with a
  higher specificity or an ``!important`` always won, or the declaration only
  repeated another rule's value. They are gone, and each removal is pinned here
  to the rule that paints instead, so removing that owner later fails loudly
  rather than silently changing the composer.
* 12 declarations became theme values of the tokens the base rules in
  ``padiem-surfaces.css`` / ``padiem-rich.css`` already read: the fade behind
  the composer, the chat-state border, shadow and note colour, and the
  textarea colour. The values are the override rules' former values, verbatim.
* 2 ``padiem-home`` declarations kept their value and lost an ``!important``
  that selector specificity already made redundant.

The 17 that remain still beat a base rule whose shape a theme token cannot
express yet (a flat surface against a two-layer gradient, a different shadow
stack, a blur literal, gradient stops fixed in the base rule, a shared text
token). The exact remainder is pinned so a re-added override or a new
``!important`` shows up as a diff here.

Sheet reads go through ``_support/theme_sheets.py`` (the structure audit
tool's parser); this module asserts on parsed rules and token values only.
"""
from __future__ import annotations

import re

from _support import theme_sheets as sheets

THEME_SHEET = "padiem-themes.css"
COMPOSER_RX = re.compile(r"\.composer(-wrap|-note)?\b")
THEMES = ("light", "dark", "cinematic", "padiem-home", "padiem-glass")

HOME_COMPOSER_BG = "linear-gradient(180deg, rgba(255,255,255,.88), rgba(250,252,255,.78))"
HOME_COMPOSER_SHADOW = "0 14px 40px rgba(26,34,48,.09), inset 0 1px 0 rgba(255,255,255,.85)"
HOME_FADE = "linear-gradient(to bottom, transparent, rgba(230,233,238,.84) 32%, var(--bg) 78%)"
LIGHT_FADE = "linear-gradient(to bottom, transparent, var(--bg) 28%, var(--bg))"
DARK_FADE = "linear-gradient(to bottom, transparent, rgba(19,20,23,.92) 34%, #131417 76%)"

#: Every composer declaration the theme sheet still carries: selector → {prop: value}.
REMAINING = {
    'html[data-theme="light"] .composer': {
        "background": "var(--composer-bg)",
        "border": "1px solid var(--composer-border)",
        "box-shadow": "var(--composer-shadow)",
    },
    'html[data-theme="light"] .composer-wrap': {"background": LIGHT_FADE},
    'html[data-theme="light"] .app-shell[data-state="chat"] .composer': {
        "background": "var(--composer-bg)",
        "backdrop-filter": "none",
    },
    'html[data-theme="light"] .composer textarea::placeholder': {"color": "var(--placeholder)"},
    'html[data-theme="dark"] .composer': {"backdrop-filter": "none"},
    'html[data-theme="cinematic"] .composer': {"backdrop-filter": "blur(16px)"},
    'html[data-theme="padiem-home"] .composer': {
        "background": HOME_COMPOSER_BG,
        "border-color": "rgba(26,34,48,.10)",
        "border-top": "1px solid rgba(255,255,255,.9)",
        "box-shadow": HOME_COMPOSER_SHADOW,
        "backdrop-filter": "blur(18px)",
    },
    'html[data-theme="padiem-home"] .composer-wrap': {"background": HOME_FADE},
    'html[data-theme="padiem-home"] .app-shell[data-state="chat"] .composer': {
        "background": HOME_COMPOSER_BG,
    },
    'html[data-theme="padiem-home"] .composer textarea::placeholder': {"color": "#7a869a"},
}

#: token → {theme: value} for every theme value this pass added. Themes not
#: listed must not declare the token (they keep the ``:root`` value).
THEME_VALUES = {
    "--surface-fade-deep": {"dark": "rgba(19,20,23,.92)", "cinematic": "rgba(4,7,13,.86)"},
    "--surface-fade-solid": {"dark": "#131417", "cinematic": "#04070d"},
    "--rich-composer-fade": {"light": LIGHT_FADE, "dark": DARK_FADE, "padiem-home": HOME_FADE},
    "--rich-composer-border": {
        "light": "var(--composer-border)",
        "padiem-home": "rgba(26,34,48,.10)",
    },
    "--rich-composer-shadow": {
        "light": "var(--composer-shadow)",
        "padiem-home": HOME_COMPOSER_SHADOW,
    },
    "--rich-composer-note": {"light": "var(--muted)", "padiem-home": "var(--muted)"},
    "--surfaces-composer-text": {
        "light": "var(--input-text)",
        "padiem-home": "var(--text-deep-ink)",
    },
}

#: Theme values that existed before this pass and are left as they were. Light,
#: padiem-home and glass alias the fade pair to their panel colour; their own
#: sheets repaint the wrap, so those aliases stay out of this contract's reach.
PRE_EXISTING = {
    "--surface-fade-deep": {"light", "padiem-home", "padiem-glass"},
    "--surface-fade-solid": {"light", "padiem-home", "padiem-glass"},
}

#: The single base declaration that reads each token: (sheet, selector, prop, value).
BASE_READERS = {
    "--surface-fade-deep": (
        "padiem-surfaces.css", ".composer-wrap", "background",
        "linear-gradient(to bottom, transparent, "
        "var(--surface-fade-deep) 34%, var(--surface-fade-solid) 76%)"),
    "--rich-composer-fade": (
        "padiem-rich.css", '.app-shell[data-state="chat"] .composer-wrap', "background",
        "var(--rich-composer-fade)"),
    "--rich-composer-border": (
        "padiem-rich.css", '.app-shell[data-state="chat"] .composer', "border-color",
        "var(--rich-composer-border)"),
    "--rich-composer-shadow": (
        "padiem-rich.css", '.app-shell[data-state="chat"] .composer', "box-shadow",
        "var(--rich-composer-shadow)"),
    "--rich-composer-note": (
        "padiem-rich.css", '.app-shell[data-state="chat"] .composer-note', "color",
        "var(--rich-composer-note) !important"),
    "--surfaces-composer-text": (
        "padiem-surfaces.css", ".composer textarea", "color",
        "var(--surfaces-composer-text)"),
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
                found.setdefault(prop, _norm(value))
    return found


def _theme_sheet_composer() -> dict[str, dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    for rule in sheets.rules(THEME_SHEET):
        if not COMPOSER_RX.search(rule.selector):
            continue
        assert len(_selectors(rule)) == 1, rule.selector
        found.setdefault(_norm(rule.selector), {}).update(
            {prop: _norm(value) for prop, value in sheets.decl_map(rule).items()})
    return found


def test_the_theme_sheet_keeps_exactly_the_blocked_composer_overrides():
    assert _theme_sheet_composer() == REMAINING


def test_no_composer_override_is_important_any_more():
    flagged = [
        (selector, prop)
        for selector, declarations in _theme_sheet_composer().items()
        for prop, value in declarations.items()
        if "!important" in value
    ]
    assert flagged == []


def test_the_moved_values_are_theme_values_of_the_base_rule_tokens():
    for token, by_theme in THEME_VALUES.items():
        for theme in THEMES:
            if theme in PRE_EXISTING.get(token, ()):
                continue
            assert sheets.token_value(theme, token) == by_theme.get(theme), (token, theme)


def test_each_token_is_read_by_exactly_one_base_declaration():
    # Giving a token a theme value is only safe while the composer rule it was
    # moved from is the one thing that reads it.
    for token, (sheet_name, selector, prop, value) in BASE_READERS.items():
        assert _declared(sheet_name, selector)[prop] == value, token
    expected = {
        (sheet_name, selector, prop)
        for sheet_name, selector, prop, _value in BASE_READERS.values()
    }
    readers = set()
    for sheet_name in sheets.shipped_sheet_names():
        if sheet_name == "padiem-tokens.css":
            continue
        for rule in sheets.rules(sheet_name):
            for prop, value in sheets.decl_map(rule).items():
                if any(f"var({token})" in value for token in THEME_VALUES):
                    for selector in _selectors(rule):
                        readers.add((sheet_name, selector, prop))
    assert readers == expected


def test_the_chat_state_note_token_keeps_the_flag_that_outranks_the_accessibility_sheet():
    # The removed chat-state note overrides were flagged because the base rule
    # is. With the value in the token, the base rule's own flag (specificity
    # 0,3,0) still outranks the accessibility sheet's themed note colour
    # (0,2,1) in the chat state — which is what keeps the theme value painting.
    base = _declared("padiem-rich.css", '.app-shell[data-state="chat"] .composer-note')
    assert base["color"].endswith("!important")
    for theme in ("light", "padiem-home"):
        chat = f'html[data-theme="{theme}"] .app-shell[data-state="chat"] .composer-note'
        assert _declared(THEME_SHEET, chat) == {}, theme


def test_the_dark_composer_box_and_text_are_painted_by_the_dark_contrast_sheet():
    box = _declared("padiem-dark-contrast.css", 'html[data-theme="dark"] body .app-shell .composer')
    assert {"background", "border", "box-shadow"} <= set(box)
    text = _declared(
        "padiem-dark-contrast.css", 'html[data-theme="dark"] body .app-shell .composer textarea')
    assert text["color"] == "#f5faff"
    placeholder = _declared(
        "padiem-dark-contrast.css",
        'html[data-theme="dark"] body .app-shell .composer textarea::placeholder')
    assert placeholder["color"] == "#b9ccdb"


def test_the_cinematic_composer_box_is_painted_by_the_readability_sheet():
    # Each box is one rule, on the body .app-shell selector (#7811 C3), so no
    # per-file rule count grows; background is the same gradient the theme
    # sheet used to repeat.
    edge = _declared("padiem-bright-readability.css", 'html[data-theme="cinematic"] body .app-shell .composer')
    assert edge["background"] == "linear-gradient(145deg, rgba(18,30,46,.8), rgba(8,11,17,.76))"
    assert edge == {
        "background": "linear-gradient(145deg, rgba(18,30,46,.8), rgba(8,11,17,.76))",
        "border-color": "rgba(136,201,255,.26)",
        "box-shadow": "0 0 40px rgba(93,178,246,.14), 0 18px 44px rgba(0,0,0,.28), inset 0 1px 0 rgba(255,255,255,.08)",
    }
    assert all("!important" not in value for value in edge.values())


def test_the_note_colour_outside_the_chat_state_is_painted_by_a_later_sheet():
    # Same selector, same specificity, later sheet, flagged: the accessibility
    # sheet outranks anything the theme sheet said about the note colour.
    expected = {
        "light": "#565e69 !important",
        "padiem-home": "#4e5968 !important",
        "cinematic": "rgba(255, 255, 255, .72) !important",
    }
    for theme, colour in expected.items():
        selector = f'html[data-theme="{theme}"] .composer-note'
        assert _declared("accessibility-polish.css", selector)["color"] == colour, theme
        assert _declared(THEME_SHEET, selector) == {}, theme
    # Dark is painted one step further on, by the dark-contrast sheet's flagged
    # text group (a longer selector than either of the rules above).
    dark = [
        rule for rule in sheets.rules_with_selector("padiem-dark-contrast.css", ".composer-note")
        if "color" in sheets.decl_map(rule)
    ]
    assert len(dark) == 1
    assert dark[0].selector.startswith('html[data-theme="dark"] body .app-shell :is(')
    assert sheets.decl_map(dark[0])["color"] == "#bdcdda !important"
    assert _declared(THEME_SHEET, 'html[data-theme="dark"] .composer-note') == {}


def test_no_theme_rule_restates_the_textarea_colour():
    # light and padiem-home now reach the textarea through the base rule's
    # token; dark and glass still paint it from their own sheets.
    for theme in ("light", "padiem-home"):
        for state in ("", ' .app-shell[data-state="chat"]'):
            selector = f'html[data-theme="{theme}"]{state} .composer textarea'
            assert _declared(THEME_SHEET, selector) == {}, selector
