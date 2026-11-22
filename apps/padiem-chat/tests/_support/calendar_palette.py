"""Parsed views for the calendar palette token contracts (#7811 C2 calendar).

The raw sheet reads live here (via claw_static); the contract tests receive
parsed rule/declaration values and assert on those, never on source text
directly.
"""
from __future__ import annotations

from css_rules import find_rules_with_selector, parse_rules
from _support.claw_static import sheet as _sheet

THEMES = ("light", "dark", "padiem-glass", "cinematic", "padiem-home")


def _blocks():
    return parse_rules(_sheet("padiem-tokens.css"))


def root_declarations() -> dict:
    roots = [r for r in find_rules_with_selector(_blocks(), ":root") if r.media is None]
    assert len(roots) == 1
    return roots[0].declarations


def theme_declarations(theme: str) -> dict:
    blocks = find_rules_with_selector(_blocks(), f'html[data-theme="{theme}"]')
    assert len(blocks) == 1, theme
    return blocks[0].declarations


def calendar_rules():
    return parse_rules(_sheet("calendar.css"))


def calendar_source() -> str:
    return _sheet("calendar.css")


def glass_defines_card_bg() -> bool:
    glass = parse_rules(_sheet("padiem-glass.css"))
    return any("--card-bg" in r.declarations for r in glass)
