"""Style contract for #7811 C2's search-sources fixed navy palette.

The research summary and answer-source cards paint one fixed navy palette in
all five themes. Their 11 color declarations now read theme-invariant tokens:
nine new ``--search-sources-*`` values owned by this sheet and the existing
``:root``-only ``--rich-response-inner-edge`` reused for the .1 hairline. The
reused name is pinned as theme-invariant, so a theme override cannot silently
repaint these cards while the raw sheet declares no color at all.

Raw sheet reads live in ``_support/calendar_palette.py``.
"""

from _support.calendar_palette import (
    search_sources_rules,
    tokens,
    unthemed_search_sources_literals,
)

SOURCES_TOKENS = {
    "--search-sources-active-edge": "rgba(31, 41, 55, 0.42)",
    "--search-sources-active-wash": "rgba(31, 41, 55, 0.07)",
    "--search-sources-summary-bg": "rgba(31, 41, 55, 0.035)",
    "--search-sources-summary-ink": "rgba(31, 41, 55, 0.66)",
    "--search-sources-answer-edge": "rgba(31, 41, 55, 0.11)",
    "--search-sources-link-wash": "rgba(31, 41, 55, 0.025)",
    "--search-sources-link-hover-wash": "rgba(31, 41, 55, 0.055)",
    "--search-sources-number-ink": "rgba(31, 41, 55, 0.62)",
    "--search-sources-copy-ink": "rgba(31, 41, 55, 0.58)",
}

REUSED_TOKENS = {
    "--rich-response-inner-edge": "rgba(31, 41, 55, 0.1)",
}


def test_all_tokens_hold_the_pre_change_literals_and_are_theme_invariant():
    found, overridden = tokens()
    for name, expected in {**SOURCES_TOKENS, **REUSED_TOKENS}.items():
        assert found.get(name) == expected, f"{name} = {found.get(name)}"
    assert all(name not in overridden for name in SOURCES_TOKENS | REUSED_TOKENS)


def test_search_sources_sheet_reads_through_every_token_not_literals():
    rules = search_sources_rules()
    values = [value for rule in rules for value in rule.declarations.values()]
    for name in SOURCES_TOKENS | REUSED_TOKENS:
        assert any(f"var({name})" in value for value in values), name
    assert unthemed_search_sources_literals() == []


def test_new_tokens_are_defined_only_in_the_token_file():
    text = "".join(
        f"{rule.selectors}{rule.declarations}" for rule in search_sources_rules()
    )
    for name in SOURCES_TOKENS:
        assert f"{name}:" not in text, name
