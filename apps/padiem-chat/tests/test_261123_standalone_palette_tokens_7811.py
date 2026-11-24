"""Style contract for #7811 C2's standalone fixed-palette tokens.

The connectors/automation standalone pages paint white card plates, ink
hairlines, read-state text and scrollbar colors with the same values in all
five themes, so ``--standalone-*`` tokens live only in ``:root`` and are
never redeclared in a theme block.  This test pins that contract and locks
the values the literals used to carry verbatim, so an accidental theme
override cannot silently repaint the standalone surfaces.  ``var(--card-bg,
#fafafa)`` lost its fallback because ``--card-bg`` is defined in every theme
(dark/light/cinematic/padiem-home in the token file, glass in
``padiem-glass.css``); ``var(--surface, ...)`` fell back because ``--surface``
is defined nowhere.  Raw reads live in ``_support/calendar_palette.py``.
"""

from _support.calendar_palette import tokens, unthemed_standalone_literals, standalone_rules

STANDALONE_TOKENS = {
    "--standalone-nav-bg": "rgba(121, 188, 231, 0.22)",
    "--standalone-card-bg": "rgba(255, 255, 255, 0.92)",
    "--standalone-card-hairline": "rgba(23, 33, 42, 0.14)",
    "--standalone-retry-border": "rgba(23, 33, 42, 0.16)",
    "--standalone-subtle-text": "#3d4c59",
    "--standalone-connected-text": "#1f5f86",
    "--standalone-state-pending": "#8a5300",
    "--standalone-state-activating": "#175cd3",
    "--standalone-state-active": "#16794c",
    "--standalone-state-failed": "#b3261e",
    "--standalone-scrollbar-thumb": "rgba(72, 91, 108, .72)",
    "--standalone-scrollbar-track": "rgba(120, 136, 148, .14)",
    "--standalone-panel-border": "rgba(255, 255, 255, .48)",
    "--standalone-panel-bg": "rgba(248, 250, 251, .28)",
    "--standalone-card-soft-bg": "rgba(255, 255, 255, .76)",
}

THEMES = ("dark", "light", "cinematic", "padiem-home", "padiem-glass")


def test_standalone_tokens_defined_once_with_the_literal_values():
    found, overridden = tokens()
    for name, expected in STANDALONE_TOKENS.items():
        assert found.get(name) == expected, f"{name} = {found.get(name)}"
    assert all(name not in overridden for name in STANDALONE_TOKENS)


def test_standalone_sheet_reads_through_tokens_not_literals():
    rules = standalone_rules()
    for name in STANDALONE_TOKENS:
        assert any(f"var({name})" in value for rule in rules for value in rule.declarations.values()), name
    assert unthemed_standalone_literals() == []


def test_card_bg_fallback_is_gone_and_resolves_in_every_theme():
    rules = standalone_rules()
    for rule in rules:
        for value in rule.declarations.values():
            assert "var(--card-bg, #fafafa)" not in value
            assert "var(--surface, rgba" not in value
