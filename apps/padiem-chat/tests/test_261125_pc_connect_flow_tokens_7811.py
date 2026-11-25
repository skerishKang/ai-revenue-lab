"""#7811 C2 pc-connect-flow.css token contract."""

from __future__ import annotations

import re

from _support.calendar_palette import root_token_families
from _support.claw_static import sheet
from css_rules import parse_rules

NEW_TOKENS = {
    "--pc-connect-flow-backdrop": "rgba(15, 16, 20, .44)",
    "--pc-connect-flow-modal-shadow": "0 18px 48px rgba(0, 0, 0, .24)",
    "--pc-connect-flow-popover-shadow": "0 12px 32px rgba(0, 0, 0, .18)",
}

REUSED_TOKENS = {
    "--project-on-ink-text": "#fff",
    "--control-wash-strong": "rgba(127, 127, 127, .14)",
    "--pc-pairing-menu-shadow": "0 8px 24px rgba(0, 0, 0, .16)",
}

DECLARATIONS = (
    (".pc-connect-backdrop", "background",
     "var(--pc-connect-flow-backdrop)", "rgba(15, 16, 20, .44)"),
    (".pc-connect-modal", "box-shadow",
     "var(--pc-connect-flow-modal-shadow)", "0 18px 48px rgba(0, 0, 0, .24)"),
    (".pc-connect-install", "color",
     "var(--project-on-ink-text)", "#fff"),
    (".pc-connect-close:hover", "background",
     "var(--control-wash-strong)", "rgba(127, 127, 127, .14)"),
    (".pc-connect-note", "box-shadow",
     "var(--pc-pairing-menu-shadow)", "0 8px 24px rgba(0, 0, 0, .16)"),
    (".pc-connect-popover", "box-shadow",
     "var(--pc-connect-flow-popover-shadow)", "0 12px 32px rgba(0, 0, 0, .18)"),
    (".pc-connect-chip-action", "color",
     "var(--project-on-ink-text)", "#fff"),
)

THEMES = ("light", "dark", "padiem-glass", "cinematic", "padiem-home")
COLOR_RX = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", re.I)
VAR_RX = re.compile(r"var\((--[a-zA-Z0-9-]+)\)")


def _token_facts():
    text = sheet("padiem-tokens.css")
    found = dict(re.findall(r"(--[\w-]+):\s*([^;]+);", text))
    overridden = set()
    for theme in THEMES:
        match = re.search(rf'html\[data-theme="{theme}"\]\s*\{{(.*?)\n\}}', text, re.S)
        assert match, theme
        overridden.update(re.findall(r"(--[\w-]+):", match.group(1)))
    return found, overridden


def _flow_rules():
    return parse_rules(sheet("pc-connect-flow.css"))


def test_new_tokens_hold_the_pre_change_literals():
    found, overridden = _token_facts()
    for name, expected in NEW_TOKENS.items():
        assert found.get(name) == expected, f"{name} = {found.get(name)}"
    assert not (set(NEW_TOKENS) & overridden), "a theme repaints a pc-connect-flow token"


def test_reused_tokens_are_defined_in_root_and_not_theme_overridden():
    found, overridden = _token_facts()
    for name, expected in REUSED_TOKENS.items():
        assert found.get(name) == expected, f"{name} = {found.get(name)}"
        assert name not in overridden, f"a theme repaints {name}"


def test_every_declaration_reads_the_expected_token_value():
    rules = _flow_rules()
    for selector, prop, after, before in DECLARATIONS:
        values = [r.declarations[prop] for r in rules
                  if selector in r.selectors and prop in r.declarations]
        assert values, (selector, prop)
        assert after in values, (selector, prop, values)
        assert before not in values, (selector, prop, values)


def test_the_sheet_carries_no_color_literals():
    for _selector, _prop, after, _before in DECLARATIONS:
        assert not COLOR_RX.search(after), after
    assert all(
        not COLOR_RX.search(value)
        for rule in _flow_rules()
        for prop, value in rule.declarations.items()
        if not prop.startswith("--")
    )


def test_every_token_is_read_by_the_sheet():
    painted = {name for rule in _flow_rules()
               for value in rule.declarations.values()
               for name in VAR_RX.findall(value)}
    assert set(NEW_TOKENS) <= painted
    assert set(REUSED_TOKENS) <= painted


def test_new_tokens_are_defined_only_in_the_token_file():
    text = "".join(
        f"{rule.selectors}{rule.declarations}" for rule in _flow_rules()
    )
    for name in NEW_TOKENS:
        assert f"{name}:" not in text, name


def test_token_family_roster_contains_exactly_the_new_tokens():
    assert root_token_families()["--pc-connect-flow"] == set(NEW_TOKENS)
