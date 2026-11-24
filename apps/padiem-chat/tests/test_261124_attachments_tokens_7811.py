"""Style contract for #7811 C2's attachments fixed-palette tokens.

``attachments.css`` paints the attachment preview and the multi-attachment
chips with one fixed light palette in all five themes. Its 17 color
declarations now read theme-invariant tokens: 12 new ``--attachments-*``
values owned by this sheet and the existing ``:root``-only
``--project-error-text`` reused for the error note. The values are pinned
verbatim to the literals they replaced, and the reused name is pinned as
theme-invariant so a later theme override cannot silently repaint these
surfaces while the raw sheet declares no color at all.

Raw sheet reads live in ``_support/calendar_palette.py``.
"""

from _support.calendar_palette import (
    attachments_rules,
    tokens,
    unthemed_attachments_literals,
)

ATTACHMENTS_TOKENS = {
    "--attachments-card-edge": "rgba(18, 31, 51, 0.12)",
    "--attachments-card-wash": "rgba(248, 250, 252, 0.92)",
    "--attachments-icon-bg": "#eef1f5",
    "--attachments-preview-note-ink": "#687386",
    "--attachments-remove-hover-wash": "rgba(18, 31, 51, 0.08)",
    "--attachments-chip-icon-ink": "#2b3a52",
    "--attachments-chip-title-ink": "#16233a",
    "--attachments-chip-meta-ink": "#5b6b80",
    "--attachments-invalid-edge": "rgba(178, 34, 34, 0.45)",
    "--attachments-invalid-wash": "rgba(255, 241, 241, 0.95)",
    "--attachments-invalid-note-ink": "#8c1d1d",
    "--attachments-chip-remove-ink": "#42526e",
}

REUSED_TOKENS = {
    "--project-error-text": "#a23434",
}


def test_all_tokens_hold_the_pre_change_literals_and_are_theme_invariant():
    found, overridden = tokens()
    for name, expected in {**ATTACHMENTS_TOKENS, **REUSED_TOKENS}.items():
        assert found.get(name) == expected, f"{name} = {found.get(name)}"
    assert all(name not in overridden for name in ATTACHMENTS_TOKENS | REUSED_TOKENS)


def test_attachments_sheet_reads_through_every_token_not_literals():
    rules = attachments_rules()
    values = [value for rule in rules for value in rule.declarations.values()]
    for name in ATTACHMENTS_TOKENS | REUSED_TOKENS:
        assert any(f"var({name})" in value for value in values), name
    assert unthemed_attachments_literals() == []


def test_new_tokens_are_defined_only_in_the_token_file():
    text = "".join(
        f"{rule.selectors}{rule.declarations}" for rule in attachments_rules()
    )
    for name in ATTACHMENTS_TOKENS:
        assert f"{name}:" not in text, name
