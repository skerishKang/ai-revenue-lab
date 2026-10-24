"""#5661: the Chat/Claw composer must share the body's lane at every width.

Past 1920px the six-panel frame lane recenters (the ≥1921px margin rule), but
the composer's left formula still used the ≤1920 terms (rail + six-panel-left
+ inset), so the body moved to the centered lane while the input stayed on the
old left edge — a 52px split at 2047px and 308px at 2560px.

The fix adds a ≥1921px composer override whose left is the same centering
expression the frame margin uses, plus the designed 14px input inset. These
assertions pin that contract; the measured production values are recorded in
the PR (#5661 report): 1440→inset 14, 1920→14, 2047→14 (was 52), 2560→14
(was 308), sidebar-collapsed and ≤920px layouts untouched.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRAME = (ROOT / "static/shared-six-panel-frame.css").read_text(encoding="utf-8")

COMPOSER_BASE = (
    'html[data-theme="padiem-glass"] body .app-shell:not(.sidebar-collapsed):is(\n'
    '    [data-state="home"], [data-state="chat"], [data-state="claw"]\n'
    "  ) .composer-wrap {\n"
    "    left: calc(var(--workspace-rail, 252px) + var(--padiem-six-panel-left) + var(--padiem-six-panel-input-inset)) !important;"
)


def test_composer_override_recenters_with_the_frame_past_1920() -> None:
    override_start = FRAME.index("#5661: past 1920px the frame lane recenters")
    override = FRAME[override_start : FRAME.index("}", FRAME.index("left: calc(", override_start)) + 1]
    assert "@media (min-width: 1921px)" in override
    assert ".composer-wrap" in override
    assert "(100vw - var(--workspace-rail, 252px) - clamp(360px, 32vw, 560px) - var(--padiem-six-panel-width)) / 2" in override
    assert "+ var(--workspace-rail, 252px)" in override
    assert "+ var(--padiem-six-panel-input-inset)" in override
    assert "!important" in override


def test_composer_override_shares_the_conversation_states_and_wins_the_cascade() -> None:
    base_index = FRAME.index(COMPOSER_BASE)
    override_index = FRAME.index("#5661: past 1920px the frame lane recenters")
    assert override_index > base_index, "the override must come after the base rule to win the cascade"
    override = FRAME[override_index : override_index + 900]
    for state in ('"home"', '"chat"', '"claw"'):
        assert state in override
    assert ":not(.sidebar-collapsed)" in override
    # The ≤1920 terms must not leak into the override.
    assert "var(--padiem-six-panel-left)" not in override


def test_frame_centering_and_composer_override_share_one_formula() -> None:
    centering = "(100vw - var(--workspace-rail, 252px) - clamp(360px, 32vw, 560px) - var(--padiem-six-panel-width)) / 2"
    assert FRAME.count(centering) == 2, "frame margin and composer left must use the same centering expression"
