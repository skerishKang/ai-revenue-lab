"""#7811 C2 pc-file-exchange.css — shared PC file dialog palette tokens.

The 9 colour declarations in ``pc-file-exchange.css`` paint the same values in
all themes. Four declarations reuse existing root-only tokens; five new
``--pc-file-exchange-*`` tokens live only in ``:root`` of ``padiem-tokens.css``.
This pins each declared value and the exact token the sheet must read, so a
theme override or a stray literal cannot repaint them.
"""

from __future__ import annotations

import re

from _support.calendar_palette import tokens as token_values
from _support.claw_static import sheet as _sheet
from css_rules import parse_rules

NEW_TOKENS = {
    "--pc-file-exchange-overlay-dim": "rgba(16, 34, 48, 0.42)",
    "--pc-file-exchange-shadow": "0 12px 40px rgba(20, 51, 73, 0.16)",
    "--pc-file-exchange-muted-text": "#5b7385",
    "--pc-file-exchange-tint": "rgba(66, 106, 135, 0.07)",
    "--pc-file-exchange-dark-panel": "rgba(22, 33, 43, 0.96)",
}

REUSED_TOKENS = frozenset({
    "--project-panel-bg", "--settings-input-bg", "--calendar-paper",
})

DECLARATIONS = (
    (".pc-exchange-overlay", "background",
     "var(--pc-file-exchange-overlay-dim)", "rgba(16, 34, 48, 0.42)"),
    (".pc-exchange-dialog", "background",
     "var(--surface, var(--project-panel-bg))", "var(--surface, rgba(255, 255, 255, 0.94))"),
    (".pc-exchange-dialog", "box-shadow",
     "var(--pc-file-exchange-shadow)", "0 12px 40px rgba(20, 51, 73, 0.16)"),
    (".pc-exchange-scope", "color",
     "var(--text-muted, var(--pc-file-exchange-muted-text))", "var(--text-muted, #5b7385)"),
    (".pc-exchange-pc", "background",
     "var(--surface, var(--settings-input-bg))", "var(--surface, rgba(255, 255, 255, 0.8))"),
    (".pc-exchange-back", "background",
     "var(--surface, var(--settings-input-bg))", "var(--surface, rgba(255, 255, 255, 0.8))"),
    (".pc-exchange-search", "background",
     "var(--field, var(--calendar-paper))", "var(--field, #fff)"),
    (".pc-exchange-entry:hover", "background",
     "var(--tint, var(--pc-file-exchange-tint))", "var(--tint, rgba(66, 106, 135, 0.07))"),
    (".pc-exchange-dialog", "background",
     "var(--surface, var(--pc-file-exchange-dark-panel))", "var(--surface, rgba(22, 33, 43, 0.96))"),
)

COLOR_RX = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", re.I)
VAR_RX = re.compile(r"var\((--[a-zA-Z0-9-]+)\)")


def _rules():
    return parse_rules(_sheet("pc-file-exchange.css"))


def test_new_tokens_hold_the_pre_change_literals():
    found, overridden = token_values()
    for name, expected in NEW_TOKENS.items():
        assert found.get(name) == expected, f"{name} = {found.get(name)}"
    assert not (set(NEW_TOKENS) & overridden), "a theme repaints a pc-exchange token"


def test_reused_tokens_are_defined_in_root_and_not_theme_overridden():
    found, overridden = token_values()
    assert REUSED_TOKENS <= set(found), "a reused token is undefined"
    assert not (REUSED_TOKENS & overridden), "a reused token is repainted by a theme"
    assert all(found[name] for name in REUSED_TOKENS)


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
    text = _sheet("pc-file-exchange.css")
    for name in NEW_TOKENS:
        assert f"{name}:" not in text, name
