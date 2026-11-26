"""Style contract for #7811 C2's util-tools accent text.

The accent buttons and the pressed platform tab paint the same white text in all
five themes. Their four ``#fff`` declarations now read one new ``--util-tools-*``
token owned by this sheet. The token stays ``:root``-only because no theme block
overrides it.

Parsing stays in this module so the PR changes only this sheet's CSS, its token
group (with SHA-256 marker) and this test.
"""

from __future__ import annotations

import re

from _support.calendar_palette import root_token_families
from _support.claw_static import sheet
from css_rules import parse_rules

SHEET_TOKENS = {
    "--util-tools-on-accent": "#fff",
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
    return parse_rules(sheet("util-tools.css"))


def test_token_group_has_its_own_family_marker():
    families = root_token_families()
    assert set(SHEET_TOKENS) <= families["--util-tools"]


def test_token_holds_the_pre_change_literal_and_is_theme_invariant():
    found, overridden = _facts()
    for name, expected in SHEET_TOKENS.items():
        assert found.get(name) == expected, f"{name} = {found.get(name)}"
    assert all(name not in overridden for name in SHEET_TOKENS)


def test_accent_text_reads_through_the_token_not_literals():
    rules = _rules()
    values = [value for rule in rules for value in rule.declarations.values()]
    for name in SHEET_TOKENS:
        assert any(f"var({name})" in value for value in values), name
    unthemed = [
        f"{rule.selectors} {prop}: {value}"
        for rule in rules if not any(THEMED.search(s) for s in rule.selectors)
        for prop, value in rule.declarations.items()
        if not prop.startswith("--") and COLOR.search(value)
    ]
    assert unthemed == []
