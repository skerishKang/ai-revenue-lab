"""Style contract for #7811 C2's rich fixed-palette tokens.

React content (answers, tables, sources) paints dark veil surfaces with the
same values in all five themes, so ``--rich-*`` tokens live only in ``:root``
and are never redeclared in a theme block.  This test pins that contract and
locks the values the literals used to carry verbatim, so an accidental theme
override cannot silently repaint the rich surfaces.  Raw reads live in
``_support/calendar_palette.py``'s sibling helper.
"""

from _support.calendar_palette import tokens, rich_rules

RICH_TOKENS = {
    "--rich-text": "rgba(247, 249, 252, .91)",
    "--rich-heading-text": "#fff",
    "--rich-quote-border": "rgba(239, 201, 132, .38)",
    "--rich-code-border": "rgba(255, 255, 255, .12)",
    "--rich-code-bg": "rgba(8, 9, 11, .76)",
    "--rich-edge": "rgba(255, 255, 255, .10)",
    "--rich-code-pre-bg": "rgba(3, 4, 6, .86)",
    "--rich-code-text": "#e8edf3",
    "--rich-table-bg": "rgba(8, 9, 11, .66)",
    "--rich-table-text": "rgba(247, 249, 252, .88)",
    "--rich-table-edge": "rgba(255, 255, 255, .08)",
    "--rich-table-head-text": "rgba(255, 255, 255, .9)",
    "--rich-research-text": "rgba(255, 255, 255, .5)",
    "--rich-link-hover-bg": "rgba(255, 255, 255, .065)",
    "--rich-source-number": "rgba(136, 201, 255, .62)",
    "--rich-source-strong": "rgba(248, 250, 253, .86)",
    "--rich-source-small": "rgba(255, 255, 255, .38)",
    "--rich-card-hover-border": "rgba(255, 255, 255, .20)",
    "--rich-composer-fade": "linear-gradient(to bottom, transparent, rgba(6, 7, 9, .88) 39%, #06080d 76%)",
    "--rich-composer-border": "rgba(255, 255, 255, .17)",
    "--rich-composer-bg-wash": "rgba(255, 255, 255, .08)",
    "--rich-composer-bg-end": "rgba(8, 9, 11, .90)",
    "--rich-composer-shadow": "inset 0 1px 0 rgba(255, 255, 255, .07), 0 30px 90px rgba(0, 0, 0, .48)",
    "--rich-composer-note": "rgba(255, 255, 255, .30)",
}

THEMES = ("dark", "light", "cinematic", "padiem-home", "padiem-glass")


def test_rich_tokens_defined_once_with_the_literal_values():
    found, overridden = tokens()
    for name, expected in RICH_TOKENS.items():
        assert found.get(name) == expected, f"{name} = {found.get(name)}"
    assert all(name not in overridden for name in RICH_TOKENS)


def test_rich_sheet_reads_through_tokens_not_literals():
    rules = rich_rules()
    for name in RICH_TOKENS:
        assert any(f"var({name})" in value for rule in rules for value in rule.declarations.values()), name
    from _support.calendar_palette import unthemed_rich_literals

    assert unthemed_rich_literals() == []


def test_no_theme_redeclares_a_rich_token():
    found, _ = tokens()
    assert found
    for name in RICH_TOKENS:
        assert name in found
