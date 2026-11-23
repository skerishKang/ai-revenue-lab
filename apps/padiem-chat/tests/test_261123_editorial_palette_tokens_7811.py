"""Style contract for #7811 C2's editorial fixed-palette tokens.

The cinematic editorial layer paints dark veil surfaces with the same
values in all five themes, so ``--editorial-*`` tokens live only in
``:root`` and are never redeclared in a theme block.  This test pins that
contract and locks the values the literals used to carry verbatim, so an
accidental theme override cannot silently repaint the editorial surfaces.
Veil-scale tokens are not reused here: ``--surface-veil-*`` and
``--line-veil-*`` are role-restricted (background/border families only),
and ``--code-header-text`` carries theme overrides.  Raw reads live in
``_support/calendar_palette.py``.
"""

from _support.calendar_palette import tokens, unthemed_editorial_literals, editorial_rules

EDITORIAL_TOKENS = {
    "--editorial-glow-top": "rgba(255, 255, 255, .055)",
    "--editorial-glow-bottom": "rgba(255, 255, 255, .025)",
    "--editorial-copy-text": "rgba(247, 249, 252, .76)",
    "--editorial-bubble-border": "rgba(255, 255, 255, .14)",
    "--editorial-bubble-wash-strong": "rgba(255, 255, 255, .085)",
    "--editorial-bubble-wash": "rgba(255, 255, 255, .045)",
    "--editorial-bubble-bg": "rgba(10, 11, 13, .64)",
    "--editorial-bubble-text": "rgba(249, 251, 253, .92)",
    "--editorial-bubble-shadow": "rgba(0, 0, 0, .13)",
    "--editorial-meta-edge": "rgba(255, 255, 255, .08)",
    "--editorial-meta-text": "rgba(255, 255, 255, .50)",
    "--editorial-line-accent": "rgba(136, 201, 255, .26)",
    "--editorial-avatar-hi": "rgba(255, 255, 255, .12)",
    "--editorial-avatar-ring": "rgba(6, 8, 13, .82)",
    "--editorial-avatar-shadow": "rgba(0, 0, 0, .2)",
    "--editorial-assistant-text": "rgba(247, 249, 252, .93)",
    "--editorial-chip-edge": "rgba(255, 255, 255, .10)",
    "--editorial-route-edge": "rgba(255, 255, 255, .18)",
    "--editorial-route-note": "rgba(255, 255, 255, .46)",
    "--editorial-typing-glow": "rgba(136, 201, 255, .38)",
    "--editorial-typing-dot": "rgba(255, 255, 255, .82)",
    "--editorial-gold-glow": "rgba(239, 201, 132, .28)",
    "--editorial-pill-edge": "rgba(255, 255, 255, .72)",
    "--editorial-faint-text": "rgba(255, 255, 255, .54)",
    "--editorial-summary-text": "rgba(255, 255, 255, .72)",
    "--editorial-note-text": "rgba(255, 255, 255, .52)",
}

THEMES = ("dark", "light", "cinematic", "padiem-home", "padiem-glass")


def test_editorial_tokens_defined_once_with_the_literal_values():
    found, overridden = tokens()
    for name, expected in EDITORIAL_TOKENS.items():
        assert found.get(name) == expected, f"{name} = {found.get(name)}"
    assert all(name not in overridden for name in EDITORIAL_TOKENS)


def test_editorial_sheet_reads_through_tokens_not_literals():
    rules = editorial_rules()
    for name in EDITORIAL_TOKENS:
        assert any(f"var({name})" in value for rule in rules for value in rule.declarations.values()), name
    assert unthemed_editorial_literals() == []
