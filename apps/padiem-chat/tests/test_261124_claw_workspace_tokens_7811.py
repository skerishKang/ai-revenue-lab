"""#7811 C2 claw-workspace.css — fixed literal palette tokens.

The 9 colour declarations in ``claw-workspace.css`` paint the same values in
all five themes. Seven new ``--workspace-canvas-*`` tokens live only in ``:root``
of ``padiem-tokens.css``; no existing root-only token had a matching value.
This pins each declared value and the exact token the sheet must read, so a
theme override or a stray literal cannot repaint them.
"""

from __future__ import annotations

import re

from _support.calendar_palette import (
    claw_workspace_rules,
    claw_workspace_source,
    tokens as token_values,
    unthemed_claw_workspace_literals,
)

NEW_TOKENS = {
    "--workspace-canvas-generate-shadow": "0 2px 10px rgba(0, 0, 0, 0.14)",
    "--workspace-canvas-error-edge": "rgba(220, 62, 62, 0.22)",
    "--workspace-canvas-error-wash": "rgba(220, 62, 62, 0.04)",
    "--workspace-canvas-approved-error-wash": "rgba(220, 62, 62, 0.07)",
    "--workspace-canvas-approved-error-edge": "rgba(220, 62, 62, 0.16)",
    "--workspace-canvas-field-edge": "rgba(15, 23, 42, 0.18)",
    "--workspace-canvas-modal-dim": "rgba(0, 0, 0, 0.72)",
}

REUSED_TOKENS: frozenset[str] = frozenset()

DECLARATIONS = (
    (".claw-generate-button", "box-shadow",
     "var(--workspace-canvas-generate-shadow)", "0 2px 10px rgba(0, 0, 0, 0.14)"),
    ('.claw-result[data-claw-state="error"] .claw-result-empty', "border-color",
     "var(--workspace-canvas-error-edge)", "rgba(220, 62, 62, 0.22)"),
    ('.claw-result[data-claw-state="error"] .claw-result-empty', "background",
     "var(--workspace-canvas-error-wash)", "rgba(220, 62, 62, 0.04)"),
    ('.claw-approved-error[data-state="error"]', "background",
     "var(--workspace-canvas-approved-error-wash)", "rgba(220, 62, 62, 0.07)"),
    ('.claw-approved-error[data-state="error"]', "border",
     "1px solid var(--workspace-canvas-approved-error-edge)", "1px solid rgba(220, 62, 62, 0.16)"),
    (".calendar-record-cancel", "border",
     "1px solid var(--border, var(--workspace-canvas-field-edge))",
     "1px solid var(--border, rgba(15, 23, 42, 0.18))"),
    (".claw-automation-rule-toggle", "border",
     "1px solid var(--border, var(--workspace-canvas-field-edge))",
     "1px solid var(--border, rgba(15, 23, 42, 0.18))"),
    (".claw-automation-rule-edit", "border",
     "1px solid var(--border, var(--workspace-canvas-field-edge))",
     "1px solid var(--border, rgba(15, 23, 42, 0.18))"),
    (".claw-pdf-preview-modal::backdrop", "background",
     "var(--workspace-canvas-modal-dim)", "rgba(0, 0, 0, 0.72)"),
)

COLOR_RX = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", re.I)
VAR_RX = re.compile(r"var\((--[a-zA-Z0-9-]+)\)")


def test_new_tokens_hold_the_pre_change_literals():
    found, overridden = token_values()
    for name, expected in NEW_TOKENS.items():
        assert found.get(name) == expected, f"{name} = {found.get(name)}"
    assert not (set(NEW_TOKENS) & overridden), "a theme repaints a claw-workspace token"


def test_every_declaration_reads_the_expected_token_value():
    rules = claw_workspace_rules()
    for selector, prop, after, before in DECLARATIONS:
        values = [r.declarations[prop] for r in rules
                  if selector in r.selectors and prop in r.declarations]
        assert values, (selector, prop)
        assert after in values, (selector, prop, values)
        assert before not in values, (selector, prop, values)


def test_the_sheet_carries_no_color_literals():
    for _selector, _prop, after, _before in DECLARATIONS:
        assert not COLOR_RX.search(after), after
    assert unthemed_claw_workspace_literals() == []


def test_every_new_token_is_read_by_the_sheet():
    painted = {name for rule in claw_workspace_rules()
               for value in rule.declarations.values()
               for name in VAR_RX.findall(value)}
    assert set(NEW_TOKENS) <= painted


def test_tokens_are_defined_only_in_the_token_file():
    for name in NEW_TOKENS:
        assert f"{name}:" not in claw_workspace_source(), name
