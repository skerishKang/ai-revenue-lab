"""Owner item 5: Chat and Claw must render one turn, and must keep two lanes.

A Claw turn is written to the same `conversations`/`messages` rows with the same
`product_scope='b62-chat'` as a Chat turn (apps/padiem-chat/app/claw_general_routes.py
vs app/chat_routes.py). Before this change the thread was styled by which mode the
shell happened to be in, so the same stored row changed appearance when the user
switched modes.

Two directions are pinned here on purpose:

* turn identity must be shared — if a rule drifts back to `[data-state="chat"]`
  only, the guard fails;
* lane geometry must stay Chat-only — the 2026-10-14 owner decision recorded in
  docs/padiem/PADIEM_CHAT_CLAW_ALIGNMENT_AUDIT_V1.md keeps Claw's body centred
  instead of copying Chat's portrait gutter, so a "helpful" widening of the lane
  rules must also fail.
"""

from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "static"

THEME = (STATIC / "theme.js").read_text(encoding="utf-8")
PORTRAIT = (STATIC / "padiem-glass-portrait.css").read_text(encoding="utf-8")
BRAND = (STATIC / "padiem-glass-brand-polish.css").read_text(encoding="utf-8")
GUTTER = (STATIC / "padiem-glass-gutter-alignment.css").read_text(encoding="utf-8")
EDITORIAL = (STATIC / "padiem-editorial.css").read_text(encoding="utf-8")
RICH = (STATIC / "padiem-rich.css").read_text(encoding="utf-8")

SHARED = ':is([data-state="chat"],[data-state="claw"])'

# (source, selector that must carry the shared gate)
TURN_IDENTITY = [
    (PORTRAIT, f"{SHARED} .assistant-meta"),
    (PORTRAIT, f"{SHARED} .assistant-avatar"),
    (PORTRAIT, f"{SHARED} #messageList .user-message.user-message"),
    (PORTRAIT, f"{SHARED} .user-message .message-bubble"),
    (BRAND, f"{SHARED} .message-list"),
    (BRAND, f"{SHARED} .assistant-message .assistant-avatar"),
    (GUTTER, f"{SHARED} .assistant-message"),
    (GUTTER, f"{SHARED} .assistant-meta"),
    (GUTTER, f"{SHARED} {{\n  --padiem-chat-meta-gap: 12px;"),
    (EDITORIAL, f"{SHARED} .assistant-content"),
    (RICH, f"{SHARED} .assistant-content"),
]


@pytest.mark.parametrize("source,selector", TURN_IDENTITY, ids=[s[1] for s in TURN_IDENTITY])
def test_turn_identity_is_one_authority_for_both_states(source, selector):
    assert selector in source, f"turn identity drifted back to a Chat-only gate: {selector}"


LANE_STAYS_CHAT_ONLY = [
    (GUTTER, 'html[data-theme="padiem-glass"] body .app-shell[data-state="chat"] {\n'
             '  --padiem-chat-reading-measure: 76ch;'),
    (GUTTER, '--padiem-chat-inner-gutter: clamp(24px, 2.5vw, 35px);'),
    (GUTTER, 'html[data-theme="padiem-glass"] body .app-shell[data-state="chat"] .conversation {\n'
             '  padding-inline: var(--padiem-chat-inner-gutter) !important;'),
]


@pytest.mark.parametrize("source,declaration", LANE_STAYS_CHAT_ONLY)
def test_lane_geometry_stays_chat_only_per_the_recorded_decision(source, declaration):
    """2026-10-14 owner decision: Claw centres its body and does not copy Chat's
    portrait gutter. Unifying the thread must not silently unify the lane."""
    assert declaration in source


def test_reading_mode_is_projected_for_a_live_claw_thread():
    """The mode is still derived from the explicit shell state, never from a
    scroll heuristic, and a Claw thread now qualifies because it is the same
    stored conversation."""
    assert 'if(shell.dataset.state==="chat") return "reading";' in THEME
    assert '.claw-workspace[data-view="general"] ~ .conversation' in THEME
    assert 'conv.querySelector("#messageList .message")' in THEME
    assert "scrollY" not in THEME.split("function glassMode()")[1].split("}")[0]


def test_the_claw_landing_keeps_the_bright_composition():
    """Presence of the conversation element is not the signal — a rendered turn
    is, so the Claw landing does not inherit the reading treatment."""
    gate = THEME.split("if(shell.dataset.state===\"claw\")")[1].split("return \"home\"")[0]
    assert 'conv.querySelector("#messageList .message")' in gate
    assert "children.length" not in gate or "querySelector" in gate
