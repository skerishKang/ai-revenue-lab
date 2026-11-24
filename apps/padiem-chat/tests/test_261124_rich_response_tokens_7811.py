"""#7811 C2 rich-response.css — fixed light palette tokens.

The 14 colour declarations in ``rich-response.css`` paint the same light values
in all five themes. Four declarations reuse existing root-only tokens; ten
read nine new ``--rich-response-*`` tokens that live only in ``:root`` of
``padiem-tokens.css``. This pins each declared value and the exact token the
sheet must read, so a theme override or a stray literal cannot repaint them.
"""

from __future__ import annotations

import re

from _support.calendar_palette import (
    rich_response_rules,
    tokens as token_values,
    unthemed_rich_response_literals,
)

NEW_TOKENS = {
    "--rich-response-quote-edge": "rgba(45, 55, 72, 0.28)",
    "--rich-response-quote-bg": "rgba(45, 55, 72, 0.045)",
    "--rich-response-rule-edge": "rgba(128, 138, 155, 0.5)",
    "--rich-response-block-edge": "rgba(31, 41, 55, 0.13)",
    "--rich-response-inner-edge": "rgba(31, 41, 55, 0.1)",
    "--rich-response-control-edge": "rgba(31, 41, 55, 0.16)",
    "--rich-response-hover-bg": "#f0f2f5",
    "--rich-response-code-bg": "#15181d",
    "--rich-response-code-text": "#eef2f7",
}

REUSED_TOKENS = frozenset({
    "--pc-connect-surface", "--surfaces-send-hover-bg", "--calendar-paper",
})

DECLARATIONS = (
    (".rich-response-quote", "border-left",
     "3px solid var(--rich-response-quote-edge)",
     "3px solid rgba(45, 55, 72, 0.28)"),
    (".rich-response-quote", "background",
     "var(--rich-response-quote-bg)", "rgba(45, 55, 72, 0.045)"),
    (".rich-response-rule", "border-top",
     "1px solid var(--rich-response-rule-edge)",
     "1px solid rgba(128, 138, 155, 0.5)"),
    (".rich-code-block", "border",
     "1px solid var(--rich-response-block-edge)",
     "1px solid rgba(31, 41, 55, 0.13)"),
    (".rich-code-block", "background",
     "var(--pc-connect-surface)", "#f7f8fa"),
    (".rich-code-header", "border-bottom",
     "1px solid var(--rich-response-inner-edge)",
     "1px solid rgba(31, 41, 55, 0.1)"),
    (".rich-code-copy", "border",
     "1px solid var(--rich-response-control-edge)",
     "1px solid rgba(31, 41, 55, 0.16)"),
    (".rich-code-copy", "background",
     "var(--surfaces-send-hover-bg)", "#fff"),
    (".rich-code-copy:hover", "background",
     "var(--rich-response-hover-bg)", "#f0f2f5"),
    (".rich-code-block pre", "background",
     "var(--rich-response-code-bg)", "#15181d"),
    (".rich-code-block pre", "color",
     "var(--rich-response-code-text)", "#eef2f7"),
    (".rich-table-block table", "background",
     "var(--calendar-paper)", "#fff"),
    (".rich-table-block td", "border-bottom",
     "1px solid var(--rich-response-inner-edge)",
     "1px solid rgba(31, 41, 55, 0.1)"),
    (".rich-table-block th", "background",
     "var(--pc-connect-surface)", "#f7f8fa"),
)

COLOR_RX = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", re.I)
VAR_RX = re.compile(r"var\((--[a-zA-Z0-9-]+)\)")


def test_new_tokens_hold_the_pre_change_literals():
    found, overridden = token_values()
    for name, expected in NEW_TOKENS.items():
        assert found.get(name) == expected, f"{name} = {found.get(name)}"
    assert not (set(NEW_TOKENS) & overridden), "a theme repaints a rich-response token"


def test_reused_tokens_are_defined_in_root_and_not_theme_overridden():
    found, overridden = token_values()
    assert REUSED_TOKENS <= set(found), "a reused token is undefined"
    assert not (REUSED_TOKENS & overridden), "a reused token is repainted by a theme"
    assert found["--pc-connect-surface"] == "#f7f8fa"
    assert found["--surfaces-send-hover-bg"] == "#fff"
    assert found["--calendar-paper"] == "#fff"


def test_every_declaration_reads_the_expected_token_value():
    rules = rich_response_rules()
    for selector, prop, after, before in DECLARATIONS:
        values = [r.declarations[prop] for r in rules
                  if selector in r.selectors and prop in r.declarations]
        assert values, (selector, prop)
        assert after in values, (selector, prop, values)
        assert before not in values, (selector, prop, values)


def test_the_sheet_carries_no_color_literals():
    for _selector, _prop, after, _before in DECLARATIONS:
        assert not COLOR_RX.search(after), after
    assert unthemed_rich_response_literals() == []


def test_every_new_token_is_read_by_the_sheet():
    painted = {name for rule in rich_response_rules()
               for value in rule.declarations.values()
               for name in VAR_RX.findall(value)}
    assert set(NEW_TOKENS) <= painted
    assert REUSED_TOKENS <= painted


def test_tokens_are_defined_only_in_the_token_file():
    from _support.calendar_palette import rich_response_source

    text = rich_response_source()
    for name in NEW_TOKENS:
        assert f"{name}:" not in text, name
