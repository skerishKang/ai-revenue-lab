"""#7811 C2 pc-pairing-card.css — fixed state palette tokens.

The 14 colour declarations in ``pc-pairing-card.css`` paint the same light state
colours in all five themes. One declaration reuses an existing root-only token;
thirteen read new ``--pc-pairing-*`` tokens that live only in ``:root`` of
``padiem-tokens.css``. This pins each declared value and the exact token the
sheet must read, so a theme override or a stray literal cannot repaint them.
"""

from __future__ import annotations

import re

from _support.calendar_palette import (
    pc_pairing_rules,
    pc_pairing_source,
    tokens as token_values,
    unthemed_pc_pairing_literals,
)

NEW_TOKENS = {
    "--pc-pairing-active-text": "#11685f",
    "--pc-pairing-active-edge": "rgba(17, 104, 95, .35)",
    "--pc-pairing-active-bg": "rgba(17, 104, 95, .08)",
    "--pc-pairing-offline-edge": "rgba(111, 112, 121, .35)",
    "--pc-pairing-offline-bg": "rgba(111, 112, 121, .08)",
    "--pc-pairing-paused-text": "#8a6d1a",
    "--pc-pairing-paused-edge": "rgba(138, 109, 26, .35)",
    "--pc-pairing-paused-bg": "rgba(138, 109, 26, .08)",
    "--pc-pairing-pending-edge": "rgba(47, 111, 153, .35)",
    "--pc-pairing-pending-bg": "rgba(47, 111, 153, .08)",
    "--pc-pairing-revoked-edge": "rgba(179, 38, 30, .35)",
    "--pc-pairing-revoked-bg": "rgba(179, 38, 30, .08)",
    "--pc-pairing-menu-shadow": "0 8px 24px rgba(0, 0, 0, .16)",
}

REUSED_TOKENS = frozenset({"--control-wash-strong"})

DECLARATIONS = (
    ('.pc-pairing-state[data-state="active"]', "color",
     "var(--pc-pairing-active-text)", "#11685f"),
    ('.pc-pairing-state[data-state="active"]', "border-color",
     "var(--pc-pairing-active-edge)", "rgba(17, 104, 95, .35)"),
    ('.pc-pairing-state[data-state="active"]', "background",
     "var(--pc-pairing-active-bg)", "rgba(17, 104, 95, .08)"),
    ('.pc-pairing-state[data-state="offline"]', "border-color",
     "var(--pc-pairing-offline-edge)", "rgba(111, 112, 121, .35)"),
    ('.pc-pairing-state[data-state="offline"]', "background",
     "var(--pc-pairing-offline-bg)", "rgba(111, 112, 121, .08)"),
    ('.pc-pairing-state[data-state="paused"]', "color",
     "var(--pc-pairing-paused-text)", "#8a6d1a"),
    ('.pc-pairing-state[data-state="paused"]', "border-color",
     "var(--pc-pairing-paused-edge)", "rgba(138, 109, 26, .35)"),
    ('.pc-pairing-state[data-state="paused"]', "background",
     "var(--pc-pairing-paused-bg)", "rgba(138, 109, 26, .08)"),
    ('.pc-pairing-state[data-state="pending_verification"]', "border-color",
     "var(--pc-pairing-pending-edge)", "rgba(47, 111, 153, .35)"),
    ('.pc-pairing-state[data-state="pending_verification"]', "background",
     "var(--pc-pairing-pending-bg)", "rgba(47, 111, 153, .08)"),
    ('.pc-pairing-state[data-state="revoked"]', "border-color",
     "var(--pc-pairing-revoked-edge)", "rgba(179, 38, 30, .35)"),
    ('.pc-pairing-state[data-state="revoked"]', "background",
     "var(--pc-pairing-revoked-bg)", "rgba(179, 38, 30, .08)"),
    (".pc-pairing-menu-panel", "box-shadow",
     "var(--pc-pairing-menu-shadow)", "0 8px 24px rgba(0, 0, 0, .16)"),
    (".pc-pairing-menu-panel > button:hover", "background",
     "var(--control-wash-strong)", "rgba(127, 127, 127, .14)"),
)

COLOR_RX = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", re.I)
VAR_RX = re.compile(r"var\((--[a-zA-Z0-9-]+)\)")


def test_new_tokens_hold_the_pre_change_literals():
    found, overridden = token_values()
    for name, expected in NEW_TOKENS.items():
        assert found.get(name) == expected, f"{name} = {found.get(name)}"
    assert not (set(NEW_TOKENS) & overridden), "a theme repaints a pc-pairing token"


def test_reused_token_is_defined_in_root_and_not_theme_overridden():
    found, overridden = token_values()
    assert REUSED_TOKENS <= set(found), "a reused token is undefined"
    assert not (REUSED_TOKENS & overridden), "a reused token is repainted by a theme"
    assert found["--control-wash-strong"] == "rgba(127, 127, 127, .14)"


def test_every_declaration_reads_the_expected_token_value():
    rules = pc_pairing_rules()
    for selector, prop, after, before in DECLARATIONS:
        values = [r.declarations[prop] for r in rules
                  if selector in r.selectors and prop in r.declarations]
        assert values, (selector, prop)
        assert after in values, (selector, prop, values)
        assert before not in values, (selector, prop, values)


def test_the_sheet_carries_no_color_literals():
    for _selector, _prop, after, _before in DECLARATIONS:
        assert not COLOR_RX.search(after), after
    assert unthemed_pc_pairing_literals() == []


def test_every_new_token_is_read_by_the_sheet():
    painted = {name for rule in pc_pairing_rules()
               for value in rule.declarations.values()
               for name in VAR_RX.findall(value)}
    assert set(NEW_TOKENS) <= painted
    assert REUSED_TOKENS <= painted


def test_tokens_are_defined_only_in_the_token_file():
    for name in NEW_TOKENS:
        assert f"{name}:" not in pc_pairing_source(), name
