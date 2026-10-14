from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
GUTTER = (STATIC / "padiem-glass-gutter-alignment.css").read_text(encoding="utf8")
PORTRAIT = (STATIC / "padiem-glass-portrait.css").read_text(encoding="utf8")


def test_first_turn_does_not_shift_composer_or_conversation():
    assert 'FIRST SCREEN = ACTIVE CHAT FRAME' in GUTTER
    assert '--padiem-chat-lane-width:' not in GUTTER
    assert '--padiem-chat-lane-offset:' not in GUTTER


def test_error_box_mirrors_avatar_and_gap_on_right():
    assert '--padiem-chat-meta-gap: 12px' in GUTTER
    assert 'grid-template-columns: 32px minmax(0, 1fr)' in GUTTER
    assert 'width: calc(100% - 32px - var(--padiem-chat-meta-gap)) !important;' in GUTTER


def test_user_bubble_is_slightly_brighter_without_geometry_changes():
    assert 'background: rgba(68, 79, 89, .90)' in PORTRAIT
    assert 'color: #f7f9fb;' in PORTRAIT
