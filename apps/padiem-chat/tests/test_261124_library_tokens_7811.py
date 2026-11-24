"""Style contract for #7811 C2's library fixed-palette tokens.

``library.css`` paints the Files tab, cards and file dialogs with one fixed
palette in all five themes. Its eight color declarations now read tokens: two
new ``--library-*`` values owned by this sheet and six existing ``:root``-only
tokens reused as-is. Every reused name is pinned as theme-invariant, so a later
theme override cannot silently repaint the library while the raw sheet
declares no color at all.

This module reads the sheets through the shared helpers rather than changing
the shared helper module, keeping the PR's changed files inside the CSS/token
contract scope.
"""

from __future__ import annotations

import re

from _support.claw_static import sheet
from css_rules import parse_rules

LIBRARY_TOKENS = {
    "--library-tab-active-edge": "rgba(47, 111, 153, 0.24)",
    "--library-dialog-dim": "rgba(15, 19, 25, 0.46)",
}

REUSED_TOKENS = {
    "--pc-pairing-pending-bg": "rgba(47, 111, 153, .08)",
    "--b66-quote-faint-edge": "rgba(127,127,127,.22)",
    "--b66-quote-hairline": "rgba(127, 127, 127, 0.28)",
    "--control-wash-soft": "rgba(127, 127, 127, 0.08)",
    "--control-wash-hover": "rgba(127, 127, 127, .16)",
    "--standalone-nav-bg": "rgba(121, 188, 231, 0.22)",
}

THEMES = ("light", "dark", "cinematic", "padiem-home", "padiem-glass")
COLOR = re.compile(r"#[0-9a-fA-F]{3,8}(?![0-9a-fA-F])|rgba?\([^()]*\)", re.I)
THEMED = re.compile(r'html\[data-theme="[^"]+"\]')


def _token_facts():
    text = sheet("padiem-tokens.css")
    found = dict(re.findall(r"(--[\w-]+):\s*([^;]+);", text))
    overridden = set()
    for theme in THEMES:
        match = re.search(rf'html\[data-theme="{theme}"\]\s*\{{(.*?)\n\}}', text, re.S)
        assert match, theme
        overridden.update(re.findall(r"(--[\w-]+):", match.group(1)))
    return found, overridden


def _library_rules():
    return parse_rules(sheet("library.css"))


def test_all_tokens_hold_the_pre_change_literals_and_are_theme_invariant():
    found, overridden = _token_facts()
    for name, expected in {**LIBRARY_TOKENS, **REUSED_TOKENS}.items():
        assert found.get(name) == expected, f"{name} = {found.get(name)}"
    assert all(name not in overridden for name in LIBRARY_TOKENS | REUSED_TOKENS)


def test_library_sheet_reads_through_every_token_not_literals():
    rules = _library_rules()
    values = [value for rule in rules for value in rule.declarations.values()]
    for name in LIBRARY_TOKENS | REUSED_TOKENS:
        assert any(f"var({name})" in value for value in values), name
    unthemed = [
        f"{rule.selectors} {prop}: {value}"
        for rule in rules if not any(THEMED.search(s) for s in rule.selectors)
        for prop, value in rule.declarations.items()
        if not prop.startswith("--") and COLOR.search(value)
    ]
    assert unthemed == []


def test_new_tokens_are_defined_only_in_the_token_file():
    text = "".join(
        f"{rule.selectors}{rule.declarations}" for rule in _library_rules()
    )
    for name in LIBRARY_TOKENS:
        assert f"{name}:" not in text, name
