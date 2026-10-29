"""#5786: the councillor page must be navigable on a phone, and its anchors must land
where they say they do.

Measured on the shipped page before this contract existed: `/councillor/councillor`
carried no `<nav>` at all, so the only way to reach 영상·사진 or 공식 채널 was to scroll
past everything above them, and six interactive controls sat under the 44px touch floor
(the activity links at 26px, the media link titles at 20px, the tile-source links at
21px, the three 의원3종 tool links at 20px, the scroll cue at 14px, the skip link at 40px).

Adding the nav then exposed a second, worse defect that this file also pins: the
header is `position: fixed`, so an anchor jump hides the heading it lands on unless
the target carries `scroll-margin-top`. The first attempt declared the offset custom
property on the topbar itself - and a custom property does not inherit sideways to a
sibling, so `#sectionActivity` and friends resolved it to nothing and every phone
jump landed under the bar. Two widths were re-measured to prove the fix, and the
inheritance rule is asserted here so it cannot silently come back.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "static" / "councillor" / "councillor.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "councillor" / "councillor.css").read_text(encoding="utf-8")
JS = (ROOT / "static" / "councillor" / "councillor.js").read_text(encoding="utf-8")

SECTIONS = ("sectionProfile", "sectionActivity", "sectionMedia", "sectionNotes", "sectionSns")


def nav_block() -> str:
    match = re.search(r'<nav[^>]*class="councillor-nav".*?</nav>', PAGE, re.S)
    assert match, "the councillor page must expose a <nav> landmark for its sections"
    return match.group(0)


def rule(selector: str) -> str:
    match = re.search(r"(?m)^" + re.escape(selector) + r"\s*\{[^}]*\}", CSS)
    assert match, f"missing rule for {selector}"
    return match.group(0)


def js_fn(name: str) -> str:
    start = JS.index("const " + name + " = ")
    brace = JS.index("{", start)
    depth = 0
    for i in range(brace, len(JS)):
        if JS[i] == "{":
            depth += 1
        elif JS[i] == "}":
            depth -= 1
            if depth == 0:
                return JS[start:i + 1]
    raise AssertionError(f"unbalanced braces in {name}")


def test_the_nav_is_an_accessible_landmark_over_every_section() -> None:
    nav = nav_block()
    assert 'aria-label="' in nav, "a second unnamed nav is not useful to a screen reader"
    for section in SECTIONS:
        assert f'href="#{section}"' in nav, f"{section} is not reachable from the nav"
        assert f'id="{section}"' in PAGE, f"{section} does not exist on the page"


def test_the_anchor_offset_is_declared_where_the_sections_can_inherit_it() -> None:
    """The bug this pins: a custom property on the topbar is invisible to <main>.

    `.councillor-topbar` and the sections are siblings, so `scroll-margin-top:
    var(--cine-anchor-offset)` on a section resolves to nothing when the value is set
    on the bar - the browser then jumps the heading underneath the fixed header.
    """
    assert re.search(r":root\s*\{[^}]*--cine-anchor-offset\s*:", CSS), \
        "the offset must be declared on :root so every section inherits it"
    assert "--cine-anchor-offset" not in rule(".councillor-topbar"), \
        "declaring the offset on the topbar again would silently un-inherit it"


def test_every_nav_target_carries_the_scroll_margin() -> None:
    targets = re.search(r"((?:#section\w+\s*,?\s*)+)\s*\{\s*([^}]*scroll-margin-top[^}]*)\}", CSS)
    assert targets, "no scroll-margin rule covers the section anchors"
    for section in SECTIONS:
        assert f"#{section}" in targets.group(1), f"{section} has no anchor offset"
    assert "var(--cine-anchor-offset)" in targets.group(2)
    assert "var(--cine-reveal-shift)" in targets.group(2)


def test_the_reveal_shift_is_one_number_shared_with_the_anchor_margin() -> None:
    """An unvisited section sits 22px below where it will end up, and the browser
    measures a jump from that shifted box - so the landing was 22px short and the top
    of the section tucked under the bar. The margin carries the same custom property
    the animation uses, because two literals would drift apart. Landing too low is
    harmless; landing under a fixed header is not."""
    shift = re.search(r"--cine-reveal-shift\s*:\s*(\d+)px", CSS)
    assert shift, "the reveal shift has no single declaration to share"
    assert "translateY(var(--cine-reveal-shift))" in CSS, "the reveal no longer reads the shared number"
    assert f"translateY({shift.group(1)}px)" not in CSS, "a second copy of the shift is free to drift"


def test_the_offset_is_measured_because_the_header_height_is_not_constant() -> None:
    """The nav wraps to its own row below the desktop breakpoint, so a constant would
    be wrong at one of the widths - the script must publish the measured bar height
    to the root, which is where the CSS reads it from."""
    assert re.search(r'documentElement\.style\.setProperty\(\s*"--cine-anchor-offset"', JS), \
        "the measured header height must be written to the element the sections inherit from"
    assert 'addEventListener("resize"' in JS, "a rotation or window resize changes the bar height"


def test_interactive_controls_meet_the_44px_floor() -> None:
    for selector in (".councillor-nav a", ".cine-timeline-link", ".cine-link-title",
                     ".councillor-skip", ".cine-tile-title a", ".cine-admin-links a"):
        body = rule(selector)
        assert re.search(r"min-height:\s*44px", body), f"{selector} has no 44px height floor"
    nav_item = rule(".councillor-nav a")
    assert re.search(r"min-width:\s*44px", nav_item), "a 44px tall but 38px wide pill is still a miss"
    # the tool row grew a 44px box; a border would float 19px under the label
    assert "border-bottom" not in rule(".cine-admin-links a"), \
        "keep the hairline on the text so the taller tap box does not detach it"


def test_the_nav_stays_one_row_on_a_phone() -> None:
    """320px is the width that decided the design: 5 labels + gaps measured 287px
    inside a 292px row. Anything that re-inflates the items pushes the header to a
    third row, and a fixed header taller than a quarter of the viewport is the
    navigation eating the page it navigates."""
    compact = re.search(r"@media \(max-width: 360px\) \{(.*?)\n\}", CSS, re.S)
    assert compact, "the 320px layout decision has no home any more"
    assert re.search(r"\.councillor-nav a \{[^}]*font-size:\s*12px", compact.group(1))
    assert re.search(r"\.councillor-nav a \{[^}]*padding:\s*0 4px", compact.group(1))


def test_the_marker_measures_layout_not_the_animation() -> None:
    """Proven in the browser: the last scroll event fires while the reveal transition is
    still moving the section, and a jump lands 22px low when the section had already
    revealed. One line against the animated rect marked the PREVIOUS section for every
    link at four widths, so the nav would lie about where the reader is."""
    body = js_fn("markCurrent")
    assert "layoutTop(" in body, "the marker reads the transformed rect again"
    assert "getBoundingClientRect" not in body, "measure layout, never the animated box"
    assert "revealShift" in body, "the landing band has to cover the reveal shift it lands inside of"
    assert "--cine-reveal-shift" in JS, "the shift must come from the same declaration the CSS animates"
    assert "offsetParent" in js_fn("layoutTop"), "offsetTop alone is relative to the offset parent"
    assert "scrollHeight" in body and "atEnd ?" in body, \
        "the last section can never reach the bar at the bottom of the page, so the line must move"


def test_the_no_js_floor_is_width_aware() -> None:
    """The nav is static markup, so it can be tapped before the script has hydrated -
    and then the CSS constant is all the jump has. One desktop constant buried the top
    of the section by 31px at 768px in the browser, because the header is 123-161px tall
    on a phone (measured), not 73px."""
    phone = re.search(r"@media \(max-width: 1000px\) \{(.*?)\n\}", CSS, re.S)
    assert phone and re.search(r":root \{ --cine-anchor-offset: 131px; \}", phone.group(1)), \
        "the 768px/390px header is 121-123px tall; the floor has to know"
    small = re.search(r"@media \(max-width: 360px\) \{(.*?)\n\}", CSS, re.S)
    assert small and re.search(r":root \{ --cine-anchor-offset: 169px; \}", small.group(1)), \
        "the 320px header wraps to 161px; the floor has to know"


def test_the_nav_draws_the_pages_own_focus_ring() -> None:
    """Measured with the keyboard: every other control gets the page's 2px accent ring,
    the nav fell back to the UA outline - one thin dark line against a video hero is
    not a focus indicator a keyboard user can follow."""
    ring = [sel for sel, body in re.findall(r"([^{}]+)\{([^}]*)\}", CSS)
            if "outline: 2px solid var(--accent" in body]
    assert ring, "the page's accent focus ring has no rule any more"
    assert any(".councillor-nav a:focus-visible" in sel for sel in ring), \
        "the nav must use the same ring every other control on the page uses"


def test_the_wrapper_still_owns_no_ai_surface() -> None:
    """Regression guard for the issue's own bar: the three tools stay PADIEM's."""
    assert "#padiem-util/speech" in JS and "#padiem-util/sns" in JS and "#padiem-util/meeting" in JS
    assert "/api/chat" not in PAGE and "/api/projects" not in PAGE, \
        "the councillor page must not grow its own generation or storage seam"
