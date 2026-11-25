"""Style contract for #7811 C2's sidebar-unified wash palette.

The unified sidebar row and its action cells use one fixed neutral palette in
all five themes. The six color declarations now name tokens: three new
``--sidebar-unified-*`` washes owned by this sheet and three existing
``:root``-only tokens reused as-is. Existing ``!important`` flags are kept
unchanged; no new one is introduced.

This module reads the sheets through shared helpers without editing them, so
the PR changes only this sheet's CSS, its token group and this test.
"""

from __future__ import annotations

import re

from _support.claw_static import sheet
from _support.calendar_palette import root_token_families
from css_rules import parse_rules

SHEET_TOKENS = {
    "--sidebar-unified-row-wash": "rgba(127,127,127,.09)",
    "--sidebar-unified-hover-wash": "rgba(127,127,127,.18)",
    "--sidebar-unified-action-hover-wash": "rgba(127,127,127,.15)",
}

REUSED_TOKENS = {
    "--editorial-chip-edge": "rgba(255, 255, 255, .10)",
    "--control-wash-strong": "rgba(127, 127, 127, .14)",
    "--b66-quote-faint-edge": "rgba(127,127,127,.22)",
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
    return parse_rules(sheet("sidebar-unified.css"))


def test_token_group_has_its_own_family_marker():
    families = root_token_families()
    assert set(SHEET_TOKENS) <= families["--sidebar-unified"]


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


def test_existing_important_count_is_unchanged_in_the_color_declarations():
    rules = _rules()
    important = sum(
        1 for rule in rules for prop, value in rule.declarations.items()
        if not prop.startswith("--") and "!important" in value
    )
    # #8340: 픽셀·계약 검증에서 차이가 나는 캡 2건만 남겼다.
    assert important == 2, important
