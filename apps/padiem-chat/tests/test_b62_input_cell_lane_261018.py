"""Owner items 2 and 3: one input cell and one frame ratio across the Glass pages.

Two defects were proven by measurement, not by reading:

1. `--padiem-six-panel-height` subtracted 100px while the frame actually sits
   inside a 78px topbar plus 16px above and below. Chat hid that because
   `flex: 1 1 0%` recomputes its height from the free space; the page views are
   `flex: 0 1 auto` and took the literal, overflowing the document by 10px at
   every viewport height.

2. The meeting transcript and the calendar/automation fields carried their own
   widget skin (radius 10px, an opaque white fill, no blur, no shadow) while
   Chat/Claw share the composer surface.

The authority for the cell is Claw's composer *at rest*. `home` is deliberately
not the reference: `padiem-first-use.css` gives the first screen a stronger
border and shadow, which is a documented state treatment, not drift.
"""

from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"

FRAME = (STATIC / "shared-six-panel-frame.css").read_text(encoding="utf-8")
GLASS = (STATIC / "padiem-glass.css").read_text(encoding="utf-8")
CLAW = (STATIC / "claw-focus-layout.css").read_text(encoding="utf-8")


def _body(css: str, selector: str) -> str:
    """Return the declaration block that follows this exact selector."""
    tail = css.split(selector, 1)[1]
    return tail.split("{", 1)[1].split("}", 1)[0]


def test_shared_frame_height_subtracts_the_topbar_and_both_margins() -> None:
    """78px topbar + 16px + 16px: the box the frame is actually laid out inside."""
    decl = [line for line in FRAME.splitlines() if "--padiem-six-panel-height:" in line]
    assert len(decl) == 1, "one height authority, not a per-page override"
    assert "calc(100dvh - 110px)" in decl[0], decl[0]
    assert "100px)" not in decl[0], "the 100px inset overflowed every viewport by 10px"


def test_the_input_inset_is_one_authority_not_two_literals() -> None:
    """The composer and the page lane must read the same inset, so a change to
    the Chat/Claw composer lane cannot silently leave the pages behind."""
    assert "--padiem-six-panel-input-inset: 14px;" in FRAME
    composer = _body(FRAME, "html[data-theme=\"padiem-glass\"] body .app-shell:not(.sidebar-collapsed):is(")
    assert "var(--padiem-six-panel-input-inset)" in composer
    assert "+ 14px)" not in composer and "- 28px)" not in composer
    assert "--padiem-six-panel-pad-x: clamp(18px, 2.4vw, 34px);" in FRAME


def test_meeting_transcript_takes_the_composer_lane() -> None:
    """Only the page-level working surface joins the composer lane."""
    rule = _body(FRAME, 'html[data-theme="padiem-glass"] body .app-shell[data-state="meeting"] #meetingTranscript')
    for declation in ("var(--padiem-six-panel-input-inset)", "var(--padiem-six-panel-pad-x)"):
        assert declation in rule, declation
    assert "#calendarRecordContent" not in rule, (
        "a multi-field grid member pulled into the composer lane measured 9px "
        "into the portrait artwork at 1920x1080")


def test_page_cells_carry_the_claw_composer_surface() -> None:
    """Item 2: the page input must compute the same skin as Claw's composer."""
    authority = _body(CLAW, "#composerForm")
    page = _body(GLASS, "#meetingTranscript, .calendar-record-field :is(input, textarea, select)")
    # Every token Claw's at-rest composer uses must also appear in the page rule.
    for token in ("border-radius: 17px", "rgba(255, 255, 255, .76)",
                  "blur(32px) saturate(104%)", "0 24px 70px rgba(28, 36, 44, .20)",
                  "inset 0 1px 0 rgba(255, 255, 255, .88)",
                  "linear-gradient(165deg, rgba(255, 255, 255, .94)"):
        assert token in authority, f"authority no longer carries {token}"
        assert token in page, f"page cells lost {token}"
    assert "font-size: 16px" in page, "Claw's composer textarea computes 16px at rest"


def test_the_cell_rule_covers_every_page_that_renders_a_field() -> None:
    """The automation page's create fields are rendered by JS, so they are absent
    from a static index.html read and invisible to a guest session; pin them in
    the selector list instead of by live measurement."""
    head = GLASS.split("One Glass input cell", 1)[1].split("html[data-theme=\"padiem-glass\"] .tool-button", 1)[0]
    for state in ("meeting", "calendar", "automation"):
        assert f'[data-state="{state}"]' in head, state
    # Four selector lists carry the cell (base, focus, and two placeholder rules).
    # A `>=` threshold is vacuous here: the literal appears on every line, so one
    # dropped occurrence still passes. Pin the count.
    for state in ("meeting", "calendar", "automation"):
        assert head.count(f'[data-state="{state}"]') == 4, (state, head.count(f'[data-state="{state}"]'))
    assert ".calendar-record-field :is(input, textarea, select)" in head


def test_the_focus_state_is_the_composer_focus_state() -> None:
    """Focus must not fall back to the browser ring on a page cell."""
    focus = _body(GLASS, "#meetingTranscript, .calendar-record-field :is(input, textarea, select)):focus")
    assert "outline: none" in focus
    assert "rgba(79, 91, 101, .22)" in focus
    assert "0 20px 54px rgba(28, 36, 44, .16)" in focus


def test_no_page_rule_fights_the_shared_cell_skin() -> None:
    """Glass-scoped guards only: the theme-agnostic base rules stay for other
    themes, but no glass rule may restate a second radius for these cells."""
    glass_pages = GLASS.split("One Glass input cell", 1)[1].split("html[data-theme=\"padiem-glass\"] .tool-button", 1)[0]
    assert glass_pages.count("border-radius: 17px") == 1, "one surface authority for page cells"
