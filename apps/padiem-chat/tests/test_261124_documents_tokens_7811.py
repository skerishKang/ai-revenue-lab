"""Style contract for #7811 C2's documents fixed-palette tokens.

``documents.css`` paints the document attachment icon and the project files
panel with one fixed light palette in all five themes. Its 14 color
declarations now read theme-invariant tokens: 9 new ``--documents-*`` values
owned by this sheet plus ``--settings-choice-fallback`` and
``--project-solid-bg`` reused as-is. Both reused names are pinned as
theme-invariant, so a later theme override cannot silently repaint these
surfaces while the raw sheet declares no color at all.

Raw sheet reads live in ``_support/calendar_palette.py``.
"""

from _support.calendar_palette import (
    documents_rules,
    tokens,
    unthemed_documents_literals,
)

DOCUMENTS_TOKENS = {
    "--documents-icon-wash": "rgba(26, 29, 33, 0.07)",
    "--documents-icon-ink": "#31343a",
    "--documents-reference-note": "#72767d",
    "--documents-banner-note": "#7a7d84",
    "--documents-panel-edge": "rgba(25, 28, 32, 0.1)",
    "--documents-muted-text": "#777b82",
    "--documents-usage-text": "#a9adb4",
    "--documents-add-edge": "rgba(25, 28, 32, 0.12)",
    "--documents-selection-outline": "#7c74f0",
}

REUSED_TOKENS = {
    "--settings-choice-fallback": "#fafafa",
    "--project-solid-bg": "#fff",
}


def test_all_tokens_hold_the_pre_change_literals_and_are_theme_invariant():
    found, overridden = tokens()
    for name, expected in {**DOCUMENTS_TOKENS, **REUSED_TOKENS}.items():
        assert found.get(name) == expected, f"{name} = {found.get(name)}"
    assert all(name not in overridden for name in DOCUMENTS_TOKENS | REUSED_TOKENS)


def test_documents_sheet_reads_through_every_token_not_literals():
    rules = documents_rules()
    values = [value for rule in rules for value in rule.declarations.values()]
    for name in DOCUMENTS_TOKENS | REUSED_TOKENS:
        assert any(f"var({name})" in value for value in values), name
    assert unthemed_documents_literals() == []


def test_new_tokens_are_defined_only_in_the_token_file():
    text = "".join(
        f"{rule.selectors}{rule.declarations}" for rule in documents_rules()
    )
    for name in DOCUMENTS_TOKENS:
        assert f"{name}:" not in text, name
