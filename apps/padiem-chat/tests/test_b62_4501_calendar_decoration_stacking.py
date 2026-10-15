"""#4501 — the Calendar destination must stack above the theme decoration.

`.main-panel::before` is a `position: fixed`, `pointer-events: none` decorative
layer. Under `padiem-glass` it carries `z-index: 1`, and the unthemed editorial
rule keeps it positioned with no z-index at all. Either way it paints above
non-positioned content, so a destination that never opts into the stacking
convention renders *underneath* the artwork: text, tabs, the record form and the
refresh control all lose contrast against the portrait.

The repository already solves this for readable surfaces: `padiem-glass-portrait.css`
lifts `.topbar`, `.conversation` and `.claw-workspace` to `position: relative;
z-index: 2`. Calendar was simply never included in that list.

These guards bind the ordering relationship rather than a single literal, so the
test fails if the Calendar rule is removed, if the decoration is raised past it,
or if someone "fixes" the bug by deleting the shared decoration.

A real-browser occlusion measurement backs this up: with the destination made
opaque, hiding the decoration changed Calendar pixels at 390px glass (help text,
tabs, record field) and at the 1280/1440 refresh control, and changed nothing
after the rule was applied.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "static"
CALENDAR_CSS = STATIC / "calendar.css"
GLASS_PORTRAIT_CSS = STATIC / "padiem-glass-portrait.css"
EDITORIAL_CSS = STATIC / "padiem-editorial.css"
STYLES_CSS = STATIC / "styles.css"


def _css(path: Path) -> str:
    """CSS with comments removed.

    The explanatory comment in calendar.css quotes the very declarations these
    guards count, so a raw-text scan would match prose. Bind the assertions to
    declarations only.
    """
    return re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.DOTALL)


def _block(css: str, selector: str) -> str:
    """Body of the first rule whose header matches `selector` exactly."""
    start = css.index(selector)
    open_brace = css.index("{", start)
    return css[open_brace + 1 : css.index("}", open_brace)]


def _z_index(body: str) -> int | None:
    match = re.search(r"z-index:\s*(-?\d+)\s*;", body)
    return None if match is None else int(match.group(1))


def _calendar_view_body() -> str:
    return _block(_css(CALENDAR_CSS), "\n.calendar-view {")


# --- the fix ------------------------------------------------------------------
def test_calendar_view_participates_in_the_stacking_convention() -> None:
    body = _calendar_view_body()
    assert "position: relative;" in body
    assert _z_index(body) is not None, "calendar.css must declare an explicit z-index"


def test_calendar_is_above_the_glass_portrait_layer() -> None:
    portrait = _css(GLASS_PORTRAIT_CSS)
    decoration_z = _z_index(_block(portrait, 'html[data-theme="padiem-glass"] .main-panel::before {'))
    calendar_z = _z_index(_calendar_view_body())
    assert decoration_z is not None, "the glass decoration must keep its own layer for this guard to mean anything"
    assert calendar_z > decoration_z, f"calendar z {calendar_z} must exceed the decoration z {decoration_z}"


def test_calendar_uses_the_same_level_as_the_other_readable_surfaces() -> None:
    # The convention value the theme already ships. If either side drifts, the
    # destination and the chat surface stop agreeing about who is readable.
    portrait = _css(GLASS_PORTRAIT_CSS)
    convention = portrait[portrait.index('html[data-theme="padiem-glass"] .topbar,') :]
    convention_z = _z_index(_block(convention, 'html[data-theme="padiem-glass"] .claw-workspace {'))
    assert convention_z is not None
    assert _z_index(_calendar_view_body()) == convention_z


def test_calendar_still_sits_under_the_chrome_it_must_not_outrank() -> None:
    styles = _css(STYLES_CSS)
    scrim = re.search(r"\.sidebar-scrim\s*\{[^}]*z-index:\s*(\d+)", styles)
    sidebar = _z_index(_block(styles, ".sidebar {"))
    calendar_z = _z_index(_calendar_view_body())
    assert scrim is not None and sidebar is not None
    assert calendar_z < int(scrim.group(1)), "the mobile scrim must stay above the destination"
    assert calendar_z < sidebar, "the sidebar must stay above the destination"


# --- the anti-patterns this fix must not turn into ---------------------------
def test_the_shared_decoration_is_not_removed_or_disabled() -> None:
    portrait = _css(GLASS_PORTRAIT_CSS)
    decoration = _block(portrait, 'html[data-theme="padiem-glass"] .main-panel::before {')
    assert "background-image: var(--padiem-glass-portrait-image);" in decoration
    assert "pointer-events: none;" in decoration
    # A Calendar-local fix must not silence the artwork globally.
    assert "display: none" not in decoration


def test_the_unthemed_editorial_decoration_is_still_positioned() -> None:
    # This is the layer that occludes Calendar outside the glass theme, so the
    # Calendar-local lift has to keep working against it.
    editorial = _block(_css(EDITORIAL_CSS), ".main-panel::before {")
    assert "position: fixed;" in editorial
    assert "pointer-events: none;" in editorial


def test_the_fix_is_scoped_to_calendar_only() -> None:
    css = _css(CALENDAR_CSS)
    assert "z-index" in css
    # Exactly one rule carries the lift: the destination itself.
    assert css.count("z-index:") == 2 and "z-index: 50;" in css
    assert ".library-view" not in css
    assert ".claw-workspace" not in css
    assert ".main-panel::before" not in css


@pytest.mark.parametrize(
    "selector",
    ["#calendarView", "#calendarTabs", "#calendarRefresh", "#calendarRecord", "#calendarList"],
)
def test_raised_destination_still_targets_the_markup_it_owns(selector: str) -> None:
    # The lift only helps if the elements that were occluded really live inside
    # the raised section rather than beside it.
    html = (STYLES_CSS.parent / "index.html").read_text(encoding="utf-8")
    band = html[html.index('id="calendarView"') : html.index('<section class="conversation"')]
    assert selector.lstrip("#") in band, f"{selector} must be inside #calendarView"
