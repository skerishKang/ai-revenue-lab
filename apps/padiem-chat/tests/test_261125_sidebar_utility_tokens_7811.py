"""#7811 C2 sidebar-utility.css — account avatar palette tokens.

The 6 colour declarations in ``sidebar-utility.css`` paint the same values in
all five themes. Three declarations reuse existing root-only tokens; three new
``--sidebar-utility-*`` tokens live only in ``:root`` of ``padiem-tokens.css``
and carry their own family SHA-256 marker. This pins the declared values and
the exact token the sheet must read, without editing shared test rosters.
"""

from __future__ import annotations

import re

from _support.calendar_palette import tokens as token_values
from _support.claw_static import sheet as _sheet
from css_rules import parse_rules

NEW_TOKENS = {
    "--sidebar-utility-avatar-ink": "#17324a",
    "--sidebar-utility-avatar-edge": "#52677a",
    "--sidebar-utility-expired-ink": "#7f1d1d",
}

REUSED_TOKENS = frozenset({
    "--editorial-typing-dot", "--calendar-visual-bg", "--calendar-paper",
})

DECLARATIONS = (
    (".sidebar-bottom .home-link:hover", "background",
     "var(--editorial-typing-dot)", "rgba(255,255,255,.82)"),
    (".account-avatar", "background",
     "var(--calendar-visual-bg)", "rgba(255,255,255,.62)"),
    (".sidebar-account .account-avatar", "color",
     "var(--sidebar-utility-avatar-ink) !important", "#17324a !important"),
    (".sidebar-account .account-avatar", "background-color",
     "var(--calendar-paper) !important", "#ffffff !important"),
    (".sidebar-account .account-avatar", "border-color",
     "var(--sidebar-utility-avatar-edge) !important", "#52677a !important"),
    ('.sidebar-account[data-account-state="expired"] .account-avatar', "color",
     "var(--sidebar-utility-expired-ink) !important", "#7f1d1d !important"),
)

COLOR_RX = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", re.I)
VAR_RX = re.compile(r"var\((--[a-zA-Z0-9-]+)\)")


def _rules():
    return parse_rules(_sheet("sidebar-utility.css"))


def test_new_tokens_hold_the_pre_change_literals():
    found, overridden = token_values()
    for name, expected in NEW_TOKENS.items():
        assert found.get(name) == expected, f"{name} = {found.get(name)}"
    assert not (set(NEW_TOKENS) & overridden), "a theme repaints a sidebar-utility token"


def test_reused_tokens_are_defined_in_root_and_not_theme_overridden():
    found, overridden = token_values()
    assert REUSED_TOKENS <= set(found), "a reused token is undefined"
    assert not (REUSED_TOKENS & overridden), "a reused token is repainted by a theme"


def test_every_declaration_reads_the_expected_token_value():
    rules = _rules()
    for selector, prop, after, before in DECLARATIONS:
        values = [r.declarations[prop] for r in rules
                  if selector in r.selectors and prop in r.declarations]
        assert values, (selector, prop)
        assert after in values, (selector, prop, values)
        assert before not in values, (selector, prop, values)


def test_sheet_carries_no_unthemed_color_literals():
    for rule in _rules():
        if rule.media is not None or any("data-theme" in s for s in rule.selectors):
            continue
        for prop, value in rule.declarations.items():
            if prop.startswith("--"):
                continue
            assert not COLOR_RX.search(value), (prop, value)


def test_every_new_token_is_read_by_the_sheet():
    painted = {name for rule in _rules()
               for value in rule.declarations.values()
               for name in VAR_RX.findall(value)}
    assert set(NEW_TOKENS) <= painted
    assert REUSED_TOKENS <= painted


def test_tokens_are_defined_only_in_the_token_file():
    for name in NEW_TOKENS:
        assert f"{name}:" not in _sheet("sidebar-utility.css"), name
