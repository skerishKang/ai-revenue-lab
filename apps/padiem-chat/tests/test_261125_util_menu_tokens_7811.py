"""Style contract for #7811 C2's util-menu PDFMD palette.

The PDFMD viewer paints one fixed palette in all five themes. Its five color
declarations now name tokens: two new ``--util-menu-*`` values owned by this
sheet and the existing ``:root``-only ``--voice-panel-bg`` reused for the white
page. The theme-overridden white text token is deliberately not reused.

Parsing stays in this module so the PR changes only this sheet's CSS, its token
group (with SHA-256 marker) and this test.
"""

from __future__ import annotations

import re

from _support.calendar_palette import root_token_families
from _support.claw_static import sheet
from css_rules import parse_rules

SHEET_TOKENS = {
    "--util-menu-pdfmd-shell-wash": "rgba(239, 243, 246, .48)",
    "--util-menu-pdfmd-warn-ink": "#8a4b0f",
}

REUSED_TOKENS = {
    "--voice-panel-bg": "#ffffff",
}

THEMES = ("light", "dark", "cinematic", "padiem-home", "padiem-glass")
COLOR = re.compile(r"#[0-9a-fA-F]{3,8}(?![0-9a-fA-F])|rgba?\([^()]*\)", re.I)
THEMED = re.compile(r'html\[data-theme="[^"]+"\]')


def _facts():
    text = sheet("padiem-tokens.css")
    found = dict(re.findall(r"(--[\w-]+):\s*([^;]+);", text))
    overridden = set()
    for theme in THEMES:
        match = re.search(rf'html\[data-theme="{theme}"\]\s*\{{(.*?)\n\}}', text, re.S)
        assert match, theme
        overridden.update(re.findall(r"(--[\w-]+):", match.group(1)))
    return found, overridden


def _rules():
    return parse_rules(sheet("util-menu.css"))


def test_token_group_has_its_own_family_marker():
    families = root_token_families()
    assert set(SHEET_TOKENS) <= families["--util-menu"]


def test_all_tokens_hold_the_pre_change_literals_and_are_theme_invariant():
    found, overridden = _facts()
    for name, expected in {**SHEET_TOKENS, **REUSED_TOKENS}.items():
        assert found.get(name) == expected, f"{name} = {found.get(name)}"
    assert all(name not in overridden for name in SHEET_TOKENS | REUSED_TOKENS)


def test_sheet_reads_through_every_token_not_literals():
    rules = _rules()
    values = [value for rule in rules for value in rule.declarations.values()]
    for name in SHEET_TOKENS | REUSED_TOKENS:
        assert any(f"var({name})" in value for value in values), name
    unthemed = [
        f"{rule.selectors} {prop}: {value}"
        for rule in rules if not any(THEMED.search(s) for s in rule.selectors)
        for prop, value in rule.declarations.items()
        if not prop.startswith("--") and COLOR.search(value)
    ]
    assert unthemed == []
