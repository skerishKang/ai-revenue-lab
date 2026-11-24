"""Style contract for #7811 C2's capability-nav fixed-palette tokens.

``capability-nav.css`` paints the Claw nav chip, the capability dialogs and
the Connectors cards with one fixed light palette in every theme. Its 19
color declarations now read theme-invariant tokens: 14 new ``--capability-nav-*``
values owned by this sheet and two existing ``:root``-only values reused as-is.
The values are pinned verbatim to the literals they replaced, and the reused
names are pinned as theme-invariant so a later theme override cannot silently
repaint these surfaces while the raw sheet declares no color at all.

Raw sheet reads live in ``_support/calendar_palette.py``.
"""

from _support.calendar_palette import (
    capability_nav_rules,
    tokens,
    unthemed_capability_nav_literals,
)

#: The 14 values owned by the capability-nav group. Each is the exact literal
#: that used to sit at the use site (including its alpha spelling).
CAPABILITY_NAV_TOKENS = {
    "--capability-nav-claw-edge": "rgba(121, 188, 231, .28)",
    "--capability-nav-claw-wash": "rgba(121, 188, 231, .10)",
    "--capability-nav-claw-badge-bg": "rgba(47, 111, 153, .18)",
    "--capability-nav-dialog-shadow": "rgba(0, 0, 0, 0.18)",
    "--capability-nav-dialog-dim": "rgba(0, 0, 0, 0.58)",
    "--capability-nav-connectors-dim": "rgba(9, 20, 30, .38)",
    "--capability-nav-connectors-surface": "rgba(255, 255, 255, .92)",
    "--capability-nav-connectors-edge": "rgba(23, 33, 42, .14)",
    "--capability-nav-connectors-edge-strong": "rgba(23, 33, 42, .16)",
    "--capability-nav-connectors-ink": "#3d4c59",
    "--capability-nav-connectors-connected-ink": "#1f5f86",
    "--capability-nav-read-pending-ink": "#8a5300",
    "--capability-nav-read-activating-ink": "#175cd3",
    "--capability-nav-read-active-ink": "#16794c",
}

#: Existing tokens reused instead of duplicating their literal. Both are
#: :root-only — unlike --accent-soft/--accent-strong/--connector-card-hairline
#: they are never redeclared in a theme block.
REUSED_TOKENS = {
    "--settings-choice-fallback": "#fafafa",
    "--project-danger-text": "#b3261e",
}


def test_all_tokens_hold_the_pre_change_literals_and_are_theme_invariant():
    found, overridden = tokens()
    for name, expected in {**CAPABILITY_NAV_TOKENS, **REUSED_TOKENS}.items():
        assert found.get(name) == expected, f"{name} = {found.get(name)}"
    assert all(name not in overridden for name in CAPABILITY_NAV_TOKENS | REUSED_TOKENS)


def test_capability_nav_sheet_reads_through_every_token_not_literals():
    rules = capability_nav_rules()
    values = [value for rule in rules for value in rule.declarations.values()]
    for name in CAPABILITY_NAV_TOKENS | REUSED_TOKENS:
        assert any(f"var({name})" in value for value in values), name
    assert unthemed_capability_nav_literals() == []


def test_new_tokens_are_defined_only_in_the_token_file():
    text = "".join(
        f"{rule.selectors}{rule.declarations}" for rule in capability_nav_rules()
    )
    for name in CAPABILITY_NAV_TOKENS:
        assert f"{name}:" not in text, name
