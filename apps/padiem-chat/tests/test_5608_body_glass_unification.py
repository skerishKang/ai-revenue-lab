"""#5608/#5028: the util and meeting bodies read as one PADIEM surface.

The production captures showed two concrete breaks against Chat/Claw:

1. The util page was the only page view missing from the shared six-panel
   frame lists, so at ≥921px its card floated centered over the portrait
   artwork while Chat/Claw/meeting sat in the reserved content lane.
2. The per-tool util panels kept their own glass skins inside that frame,
   which double-insets the content — the same defect #5028 fixed for
   .meeting-panel — and the SNS platform switcher shipped markup with no
   skin, so blog/facebook/instagram rendered as raw browser buttons.

Static assertions pin the frame membership and the flattening/grid/button
contracts; heights and colors stay tunable and are not pinned here.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRAME = (ROOT / "static/shared-six-panel-frame.css").read_text(encoding="utf-8")
UTIL_CSS = (ROOT / "static/util-menu.css").read_text(encoding="utf-8")
MEETING_CSS = (ROOT / "static/meeting-capture.css").read_text(encoding="utf-8")


def test_util_view_joins_every_six_panel_frame_lane() -> None:
    frame_lists = [segment for segment in FRAME.split(":is(") if ".meeting-view" in segment]
    assert len(frame_lists) >= 4, "expected the frame, ultrawide, eyebrow and collapse lanes"
    for segment in frame_lists:
        assert ".util-view" in segment, "a six-panel lane is missing .util-view"


def test_util_tool_panels_flatten_inside_the_glass_frame() -> None:
    block = UTIL_CSS[UTIL_CSS.index("#5028/#5608: inside the shared six-panel frame") : UTIL_CSS.index(".util-sns-tabs {")]
    assert "@media (min-width: 921px)" in block
    assert 'html[data-theme="padiem-glass"] body .app-shell[data-state="util"]' in block
    for selector in ("#utilSpeechPanel", "#utilSnsPanel", "#utilMeetingPanel", ".pdfmd-shell"):
        assert selector in block
    assert "padding: 0" in block and "box-shadow: none" in block
    assert "backdrop-filter: none" in block


def test_util_forms_pair_short_fields_and_span_textareas() -> None:
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in UTIL_CSS
    assert ".util-form label:has(textarea) { grid-column: 1 / -1; }" in UTIL_CSS


def test_sns_platform_switcher_is_skinned() -> None:
    assert ".util-sns-tabs { display: flex; flex-wrap: wrap; gap: 8px; }" in UTIL_CSS
    assert ".util-sns-tab {" in UTIL_CSS
    assert "min-height: 44px" in UTIL_CSS
    assert ".util-sns-tab.active {" in UTIL_CSS
    assert ".util-sns-tab:focus-visible {" in UTIL_CSS


def test_meeting_transcript_height_is_capped_for_the_first_screen() -> None:
    assert "min-height: clamp(200px, 30vh, 330px)" in MEETING_CSS
