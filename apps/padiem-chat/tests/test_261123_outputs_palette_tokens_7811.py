"""Style contract for #7811 C2's saved-output dialog palette tokens.

``outputs.css`` paints the saved-answer dialog with the same fixed light
palette as ``projects.css`` in all five themes.  Thirteen values therefore
reuse the theme-invariant ``--project-*`` tokens; only the two alphas that
palette did not own and the dialog shadow this sheet owns get ``--outputs-*``
tokens.  The reused names are pinned here as theme-invariant as well, so a
later theme override cannot silently repaint this dialog while the raw sheet
declares no colors at all.
"""

from _support.calendar_palette import tokens, outputs_rules, unthemed_outputs_literals

REUSED_TOKENS = {
    "--project-border": "rgba(24, 24, 27, 0.12)",
    "--project-danger-text": "#b3261e",
    "--project-dim": "rgba(20, 20, 24, 0.34)",
    "--project-focus-outline": "rgba(24, 24, 27, 0.16)",
    "--project-hairline": "rgba(24, 24, 27, 0.1)",
    "--project-hover-border": "rgba(24, 24, 27, 0.14)",
    "--project-ink": "#18181b",
    "--project-muted-text": "#5f6368",
    "--project-note-text": "#777c85",
    "--project-on-ink-text": "#fff",
    "--project-secondary-text": "#8a8f98",
    "--project-solid-bg": "#fff",
    "--project-subtle-wash": "rgba(24, 24, 27, 0.06)",
}

OUTPUTS_TOKENS = {
    "--outputs-action-hover-wash": "rgba(24, 24, 27, 0.05)",
    "--outputs-content-bg": "rgba(24, 24, 27, 0.025)",
    "--outputs-dialog-shadow": "rgba(24, 24, 27, 0.2)",
}


def test_reused_and_new_tokens_hold_the_pre_change_literals():
    found, overridden = tokens()
    for name, expected in {**REUSED_TOKENS, **OUTPUTS_TOKENS}.items():
        assert found.get(name) == expected, f"{name} = {found.get(name)}"
    assert all(name not in overridden for name in REUSED_TOKENS | OUTPUTS_TOKENS)


def test_outputs_sheet_reads_through_tokens_not_literals():
    rules = outputs_rules()
    for name in REUSED_TOKENS | OUTPUTS_TOKENS:
        assert any(f"var({name})" in value for rule in rules for value in rule.declarations.values()), name
    assert unthemed_outputs_literals() == []


def test_outputs_tokens_are_defined_only_in_the_token_file():
    text = "".join(
        f"{rule.selectors}{rule.declarations}" for rule in outputs_rules()
    )
    for name in OUTPUTS_TOKENS:
        assert f"{name}:" not in text, name
