"""Style contract for #7811 C2's b66-quote-runtime fallback palette.

The quote dialog and connection cards put fixed literals inside ``var()``
fallbacks. Their 13 color declarations now name tokens: five new
``--b66-quote-*`` values owned by this sheet and four existing ``:root``-only
tokens reused for the white surfaces and the focus outline. Every reused name
is pinned as theme-invariant, so a theme override cannot silently repaint the
dialog while the raw sheet declares no color at all.

Raw sheet reads live in ``_support/calendar_palette.py``.
"""

from _support.calendar_palette import (
    b66_quote_rules,
    tokens,
    unthemed_b66_quote_literals,
)

QUOTE_TOKENS = {
    "--b66-quote-hairline": "rgba(127, 127, 127, 0.28)",
    "--b66-quote-dialog-dim": "rgba(0, 0, 0, 0.55)",
    "--b66-quote-edge": "rgba(127,127,127,.3)",
    "--b66-quote-faint-edge": "rgba(127,127,127,.22)",
    "--b66-quote-review-surface": "rgba(255, 255, 255, 0.7)",
}

REUSED_TOKENS = {
    "--surface-veil-faint": "rgba(255, 255, 255, .05)",
    "--surface-veil-panel": "rgba(255, 255, 255, .04)",
    "--pc-focus": "#2a7db4",
    "--settings-input-bg": "rgba(255, 255, 255, .8)",
}


def test_all_tokens_hold_the_pre_change_literals_and_are_theme_invariant():
    found, overridden = tokens()
    for name, expected in {**QUOTE_TOKENS, **REUSED_TOKENS}.items():
        assert found.get(name) == expected, f"{name} = {found.get(name)}"
    assert all(name not in overridden for name in QUOTE_TOKENS | REUSED_TOKENS)


def test_quote_sheet_reads_through_every_token_not_literals():
    rules = b66_quote_rules()
    values = [value for rule in rules for value in rule.declarations.values()]
    for name in QUOTE_TOKENS | REUSED_TOKENS:
        assert any(f"var({name})" in value for value in values), name
    assert unthemed_b66_quote_literals() == []


def test_new_tokens_are_defined_only_in_the_token_file():
    text = "".join(
        f"{rule.selectors}{rule.declarations}" for rule in b66_quote_rules()
    )
    for name in QUOTE_TOKENS:
        assert f"{name}:" not in text, name
