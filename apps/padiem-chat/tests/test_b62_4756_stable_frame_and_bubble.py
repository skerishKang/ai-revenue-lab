"""#4756 frame guards + the Plan 4 (#4951) user-turn contract.

The user turn no longer draws a bubble surface, so the original "slightly brighter
bubble" premise is superseded; what must stay pinned is that no surface comes back
and that the geometry stays the three-column Plan 4 grid.
"""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
GUTTER = (STATIC / "padiem-glass-gutter-alignment.css").read_text(encoding="utf8")
PORTRAIT = (STATIC / "padiem-glass-portrait.css").read_text(encoding="utf8")
RULES = [(sel.strip(), body) for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", PORTRAIT)]
BUBBLE_SELECTOR_FRAGMENT = ".user-message .message-bubble"


def blocks_with(selector_part):
    return [body for sel, body in RULES if selector_part in sel]


def declarations(body, prop):
    pattern = rf"(?<![-\w]){prop}\s*:\s*([^;]+);"
    return [value.replace("!important", "").strip() for value in re.findall(pattern, body)]


def test_first_turn_does_not_shift_composer_or_conversation():
    assert 'FIRST SCREEN = ACTIVE CHAT FRAME' in GUTTER
    assert '--padiem-chat-lane-width:' not in GUTTER
    assert '--padiem-chat-lane-offset:' not in GUTTER


def test_error_box_mirrors_avatar_and_gap_on_right():
    assert '--padiem-chat-meta-gap: 12px' in GUTTER
    assert 'grid-template-columns: 32px minmax(0, 1fr)' in GUTTER
    assert 'width: calc(100% - 32px - var(--padiem-chat-meta-gap)) !important;' in GUTTER


def test_user_turn_has_no_bubble_surface_in_either_state():
    surfaces = blocks_with(BUBBLE_SELECTOR_FRAGMENT)
    assert surfaces, "the Glass user-turn bubble rules disappeared from the portrait layer"
    for body in surfaces:
        for prop in ("background", "background-color"):
            for value in declarations(body, prop):
                assert value in ("none", "transparent"), (
                    f"the user turn regained a bubble surface: {prop}: {value}"
                )
    # The removal has to stay stated explicitly, so re-introducing a surface means
    # editing a pinned line instead of slipping a new declaration in silently.
    pinned = [body for body in surfaces if "background: none" in body]
    assert pinned, "no Glass user-bubble rule declares the surface removal"
    assert any("box-shadow: none !important" in body for body in pinned)


def test_user_turn_mirrors_the_answer_typography_in_both_states():
    """One thread, one typography.

    This test used to pin two different values — #111a22/17px in Chat and
    #17212a/16px in Claw — which is precisely the defect the owner reported as
    "the two conversations look different". A Claw turn is stored in the same
    conversation row as a Chat turn, so the mirroring must now hold identically
    in both, and the Claw-only rule must be gone rather than merely unused.
    """
    shared = " ".join(
        blocks_with(':is([data-state="chat"],[data-state="claw"]) .user-message .message-bubble')
    )
    assert "color: #111a22" in shared
    assert "font-size: 17px" in shared
    claw_only = blocks_with('[data-state="claw"] .user-message .message-bubble')
    assert claw_only == [], f"a Claw-only bubble rule re-split the thread: {claw_only}"


def test_plan4_three_column_grid_and_chip_geometry_stay_pinned():
    turn = " ".join(blocks_with("#messageList .user-message.user-message"))
    assert "grid-template-columns: minmax(0, 1fr) auto 32px !important" in turn
    avatar = " ".join(blocks_with("#messageList .user-message .user-avatar"))
    assert "width: 32px !important" in avatar
    assert "height: 32px !important" in avatar
    chip = " ".join(blocks_with("#messageList .user-message .user-profile-chip"))
    assert "font-weight: 700 !important" in chip
    assert "color: #53606c !important" in chip


def test_superseded_dark_bubble_literals_stay_removed():
    assert "rgba(68, 79, 89" not in PORTRAIT
    assert "#f7f9fb" not in PORTRAIT
