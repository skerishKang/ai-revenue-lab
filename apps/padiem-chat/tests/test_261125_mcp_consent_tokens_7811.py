"""Style contract for #7811 C2's mcp-oauth-consent fixed palette.

The consent document is loaded outside the themed app shell, so its fixed
palette keeps the same values everywhere. Its seven color declarations now
read tokens: four new ``--mcp-consent-*`` values owned by this sheet and three
existing ``:root``-only tokens reused as-is. Every reused name is pinned as
theme-invariant, so a theme override cannot silently repaint the consent
screen while the raw sheet declares no color at all.

Parsing stays inside this module so the PR changes only CSS, token tests and
evidence, as required by the reduced CI scope.
"""

from __future__ import annotations

import re

from _support.claw_static import sheet
from css_rules import parse_rules

CONSENT_TOKENS = {
    "--mcp-consent-gold-wash": "rgba(212, 173, 104, 0.16)",
    "--mcp-consent-card-shadow": "rgba(38, 35, 31, 0.10)",
    "--mcp-consent-capability-wash": "rgba(47, 93, 80, 0.07)",
    "--mcp-consent-scope-edge": "#d8d8e0",
}

REUSED_TOKENS = {
    "--answer-actions-bg": "rgba(255, 255, 255, 0.55)",
    "--project-solid-bg": "#fff",
    "--project-on-ink-text": "#fff",
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


def _consent_rules():
    return parse_rules(sheet("mcp-oauth-consent.css"))


def test_all_tokens_hold_the_pre_change_literals_and_are_theme_invariant():
    found, overridden = _token_facts()
    for name, expected in {**CONSENT_TOKENS, **REUSED_TOKENS}.items():
        assert found.get(name) == expected, f"{name} = {found.get(name)}"
    assert all(name not in overridden for name in CONSENT_TOKENS | REUSED_TOKENS)


def test_consent_sheet_reads_through_every_token_not_literals():
    rules = _consent_rules()
    values = [value for rule in rules for value in rule.declarations.values()]
    for name in CONSENT_TOKENS | REUSED_TOKENS:
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
        f"{rule.selectors}{rule.declarations}" for rule in _consent_rules()
    )
    for name in CONSENT_TOKENS:
        assert f"{name}:" not in text, name
