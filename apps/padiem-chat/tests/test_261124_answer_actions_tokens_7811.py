"""#7811 C2 answer-actions.css — fixed accent palette tokens.

The 11 colour declarations in ``answer-actions.css`` paint the same accent
values in all five themes. One declaration reuses an existing root-only token;
nine new ``--answer-actions-*`` tokens live only in ``:root`` of
``padiem-tokens.css``. This pins each declared value and the exact token the
sheet must read, so a theme override or a stray literal cannot repaint them.
"""

from __future__ import annotations

import re

from _support.calendar_palette import (
    answer_actions_rules,
    answer_actions_source,
    tokens as token_values,
    unthemed_answer_actions_literals,
)

NEW_TOKENS = {
    "--answer-actions-avatar-wash": "rgba(101, 87, 232, 0.12)",
    "--answer-actions-avatar-edge": "rgba(101, 87, 232, 0.28)",
    "--answer-actions-time-text": "#7b8792",
    "--answer-actions-edge": "rgba(101, 87, 232, 0.22)",
    "--answer-actions-bg": "rgba(255, 255, 255, 0.55)",
    "--answer-actions-text": "#4c3fd1",
    "--answer-actions-hover-edge": "rgba(101, 87, 232, 0.45)",
    "--answer-actions-pressed-bg": "rgba(101, 87, 232, 0.16)",
    "--answer-actions-more-bg": "rgba(255, 255, 255, 0.7)",
}

REUSED_TOKENS = frozenset({"--ws-input-text"})

DECLARATIONS = (
    (".user-avatar", "background",
     "var(--answer-actions-avatar-wash)", "rgba(101, 87, 232, 0.12)"),
    (".user-avatar", "border",
     "1px solid var(--answer-actions-avatar-edge)", "1px solid rgba(101, 87, 232, 0.28)"),
    (".answer-action-time", "color",
     "var(--answer-actions-time-text)", "#7b8792"),
    (".answer-action", "border",
     "1px solid var(--answer-actions-edge)", "1px solid rgba(101, 87, 232, 0.22)"),
    (".answer-action", "background",
     "var(--answer-actions-bg)", "rgba(255, 255, 255, 0.55)"),
    (".answer-action", "color",
     "var(--answer-actions-text)", "#4c3fd1"),
    (".answer-action:hover", "background",
     "var(--ws-input-text)", "rgba(255, 255, 255, 0.9)"),
    (".answer-action:hover", "border-color",
     "var(--answer-actions-hover-edge)", "rgba(101, 87, 232, 0.45)"),
    ('.answer-action[aria-pressed="true"]', "background",
     "var(--answer-actions-pressed-bg)", "rgba(101, 87, 232, 0.16)"),
    (".answer-more-menu", "border",
     "1px solid var(--answer-actions-edge)", "1px solid rgba(101, 87, 232, 0.22)"),
    (".answer-more-menu", "background",
     "var(--answer-actions-more-bg)", "rgba(255, 255, 255, 0.7)"),
)

COLOR_RX = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", re.I)
VAR_RX = re.compile(r"var\((--[a-zA-Z0-9-]+)\)")


def test_new_tokens_hold_the_pre_change_literals():
    found, overridden = token_values()
    for name, expected in NEW_TOKENS.items():
        assert found.get(name) == expected, f"{name} = {found.get(name)}"
    assert not (set(NEW_TOKENS) & overridden), "a theme repaints an answer-actions token"


def test_reused_token_is_defined_in_root_and_not_theme_overridden():
    found, overridden = token_values()
    assert REUSED_TOKENS <= set(found), "a reused token is undefined"
    assert not (REUSED_TOKENS & overridden), "a reused token is repainted by a theme"
    assert found["--ws-input-text"] == "rgba(255, 255, 255, .9)"


def test_every_declaration_reads_the_expected_token_value():
    rules = answer_actions_rules()
    for selector, prop, after, before in DECLARATIONS:
        values = [r.declarations[prop] for r in rules
                  if selector in r.selectors and prop in r.declarations]
        assert values, (selector, prop)
        assert after in values, (selector, prop, values)
        assert before not in values, (selector, prop, values)


def test_the_sheet_carries_no_color_literals():
    for _selector, _prop, after, _before in DECLARATIONS:
        assert not COLOR_RX.search(after), after
    assert unthemed_answer_actions_literals() == []


def test_every_new_token_is_read_by_the_sheet():
    painted = {name for rule in answer_actions_rules()
               for value in rule.declarations.values()
               for name in VAR_RX.findall(value)}
    assert set(NEW_TOKENS) <= painted
    assert REUSED_TOKENS <= painted


def test_tokens_are_defined_only_in_the_token_file():
    for name in NEW_TOKENS:
        assert f"{name}:" not in answer_actions_source(), name
