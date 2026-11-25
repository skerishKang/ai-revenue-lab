"""#7811 C2 meeting-capture.css token contract."""

from __future__ import annotations

import hashlib
import re

from _support.calendar_palette import tokens as token_values
from _support.claw_static import sheet as _sheet
from css_rules import parse_rules

NEW_TOKENS = {
    "--meeting-capture-panel-edge": "rgba(128,128,128,.28)",
    "--meeting-capture-panel-shadow": "0 14px 45px rgba(20,30,44,.10)",
}

REUSED_TOKENS = {
    "--standalone-nav-bg": "rgba(121, 188, 231, 0.22)",
    "--project-solid-bg": "#fff",
    "--project-on-ink-text": "#fff",
}

DECLARATIONS = (
    ('#meetingNavButton[aria-current="page"]', "background",
     "var(--standalone-nav-bg)", "rgba(121, 188, 231, 0.22)"),
    (".meeting-panel", "border",
     "1px solid var(--glass-chat-border, var(--border, var(--meeting-capture-panel-edge)))",
     "1px solid var(--glass-chat-border, var(--border, rgba(128,128,128,.28)))"),
    (".meeting-panel", "background",
     "var(--glass-card-surface, var(--card-bg, var(--surface, var(--project-solid-bg))))",
     "var(--glass-card-surface, var(--card-bg, var(--surface, #fff)))"),
    (".meeting-panel", "box-shadow",
     "var(--card-shadow, var(--meeting-capture-panel-shadow))",
     "var(--card-shadow, 0 14px 45px rgba(20,30,44,.10))"),
    (".meeting-controls #meetingStart", "color",
     "var(--project-on-ink-text)", "#fff"),
)

COLOR_RX = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", re.I)
THEMED_RX = re.compile(r'html\[data-theme="[^"]+"\]')
VAR_RX = re.compile(r"var\((--[a-zA-Z0-9-]+)\)")


def _rules():
    return parse_rules(_sheet("meeting-capture.css"))


def test_new_tokens_hold_the_pre_change_literals():
    found, overridden = token_values()
    for name, expected in NEW_TOKENS.items():
        assert found.get(name) == expected, f"{name} = {found.get(name)}"
    assert not (set(NEW_TOKENS) & overridden), "a theme repaints a meeting-capture token"


def test_reused_tokens_are_defined_in_root_and_not_theme_overridden():
    found, overridden = token_values()
    for name, expected in REUSED_TOKENS.items():
        assert found.get(name) == expected, f"{name} = {found.get(name)}"
        assert name not in overridden, f"a theme repaints {name}"


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
        if any(THEMED_RX.search(selector) for selector in rule.selectors):
            continue
        for prop, value in rule.declarations.items():
            if not prop.startswith("--"):
                assert not COLOR_RX.search(value), (prop, value)


def test_every_token_is_read_by_the_sheet():
    painted = {name for rule in _rules()
               for value in rule.declarations.values()
               for name in VAR_RX.findall(value)}
    assert set(NEW_TOKENS) <= painted
    assert set(REUSED_TOKENS) <= painted


def test_new_tokens_are_defined_only_in_the_token_file():
    for name in NEW_TOKENS:
        assert f"{name}:" not in _sheet("meeting-capture.css"), name


def test_token_family_marker_matches_the_new_roster():
    text = _sheet("padiem-tokens.css")
    match = re.search(
        r"#7811 token-family --meeting-capture sha256=([a-f0-9]{64})", text)
    assert match
    expected = hashlib.sha256("\n".join(sorted(NEW_TOKENS)).encode("utf-8")).hexdigest()
    assert match.group(1) == expected
