"""#4515 — the Calendar controls must expose a >=44x44 CSS px hit area.

CLO2 measured the shipped Calendar controls at 390px as **refresh ~33px high,
category tabs ~41px, record input ~37px**, below the project's 44px minimum
touch-target aspiration. A real-browser probe at exact main reproduced those
boxes (refresh 38x33, tab 40.39px tall and 32.25px wide for a one-character
label, date/text field 36.8-38.8px, appointment `<select>` 19px) and confirmed
the fix at 390/920/1280/1440 in glass/light/dark.

These guards bind the *floor*, not the arithmetic that happens to produce it, so
the test keeps passing if someone later re-tunes the padding — and fails if the
floor is dropped, if the glyph is inflated to fake a bigger target, or if the
change leaks into the #4501 stacking fix or the shared surfaces.

The 44px minimum is a hit-area requirement, not a type-size change: every guard
that pins a font-size exists to catch "fixed it by making the text bigger".
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "static"
CALENDAR_CSS = STATIC / "calendar.css"

REFRESH = r"\.calendar-refresh-button\s*\{"
TAB = r"\.calendar-tab\s*\{"
RECORD_FIELDS = r"\.calendar-record-field input,\s*\.calendar-record-field textarea\s*\{"
RECORD_SELECT = r"\.calendar-record-field select\s*\{"
CALENDAR_VIEW = r"\.calendar-view\s*\{"


def _css(path: Path = CALENDAR_CSS) -> str:
    """CSS with comments removed, so prose cannot satisfy a declaration guard."""
    return re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.DOTALL)


def _rule(css: str, header: str) -> str:
    """Body of the first rule whose header matches `header` (a regex)."""
    match = re.search(header, css)
    assert match is not None, f"rule not found: {header}"
    open_brace = css.index("{", match.start())
    return css[open_brace + 1 : css.index("}", open_brace)]


def _declares(body: str, declaration: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(declaration)}(?![\w-])", body) is not None


# --- the fix ------------------------------------------------------------------


def test_refresh_control_meets_the_44px_floor() -> None:
    body = _rule(_css(), REFRESH)
    assert _declares(body, "min-height: 44px"), "the refresh hit area must be >=44px tall"
    assert _declares(body, "min-width: 44px"), "the single-glyph refresh box must be >=44px wide"
    # The glyph must be centred inside the grown box, not pushed to a corner.
    assert _declares(body, "display: inline-flex")
    assert _declares(body, "align-items: center")
    assert _declares(body, "justify-content: center")


def test_category_tabs_meet_the_44px_floor() -> None:
    body = _rule(_css(), TAB)
    assert _declares(body, "min-height: 44px"), "tabs measured 40.4px tall"
    assert _declares(body, "min-width: 44px"), "one-character tabs (일/주/월) measured 32.25px wide"
    assert _declares(body, "display: inline-flex")
    assert _declares(body, "align-items: center")


def test_record_inputs_meet_the_44px_floor() -> None:
    body = _rule(_css(), RECORD_FIELDS)
    assert _declares(body, "min-height: 44px"), "the single-line record/event fields measured 36.8-38.8px"


def test_appointment_selects_meet_the_44px_floor() -> None:
    # UA-styled selects rendered at 19px — the smallest target in the surface.
    body = _rule(_css(), RECORD_SELECT)
    assert _declares(body, "min-height: 44px")


# --- the anti-patterns this fix must not turn into ---------------------------


@pytest.mark.parametrize(
    ("header", "font_size"),
    [
        (REFRESH, "font-size: 15px"),
        (TAB, "font-size: 14px"),
        (RECORD_FIELDS, "font-size: 13px"),
    ],
)
def test_the_floor_grows_the_hit_area_not_the_glyph(header: str, font_size: str) -> None:
    # "Fix it by making the text bigger" would satisfy a naive 44px check while
    # wrecking the type scale. The shipped type sizes must survive verbatim.
    body = _rule(_css(), header)
    assert _declares(body, font_size), f"{header} must keep its shipped {font_size}"


@pytest.mark.parametrize("header", [REFRESH, TAB, RECORD_FIELDS, RECORD_SELECT])
def test_no_fixed_height_or_scale_hack_caps_the_floor(header: str) -> None:
    body = _rule(_css(), header)
    # A fixed `height` would fight `min-height`, and a transform would fake a
    # hit area that the browser does not actually route touches to.
    assert not re.search(r"(?<![\w-])height:\s*\d", body), "use min-height, not a fixed height"
    assert "transform:" not in body
    assert "scale(" not in body


def test_the_shipped_padding_and_line_box_are_preserved() -> None:
    # The fix is additive: the original geometry stays and the floor is layered
    # on top, so nothing about the visual box changes except its minimum size.
    assert _declares(_rule(_css(), REFRESH), "padding: 8px 12px")
    assert _declares(_rule(_css(), REFRESH), "line-height: 1")
    assert _declares(_rule(_css(), TAB), "padding: 8px 14px")
    assert _declares(_rule(_css(), RECORD_FIELDS), "padding: 7px 10px")


def test_tabs_keep_their_selected_underline_contract() -> None:
    css = _css()
    assert _declares(_rule(css, TAB), "border-bottom: 2px solid transparent")
    selected = _rule(css, r'\.calendar-tab\[aria-selected="true"\]\s*\{')
    assert "border-bottom-color:" in selected
    # The narrow-viewport strip must stay horizontally scrollable rather than
    # letting the wider tabs push the page sideways.
    assert "overflow-x: auto" in css


# --- boundaries this slice must respect --------------------------------------


def test_the_4501_stacking_fix_is_preserved() -> None:
    body = _rule(_css(), CALENDAR_VIEW)
    assert _declares(body, "position: relative")
    assert re.search(r"z-index:\s*2\s*;", body), "the #4501 lift must survive verbatim"
    # Exactly one z-index in the file: this slice adds geometry, not layers.
    assert _css().count("z-index:") == 2 and "z-index: 50;" in _css()


def test_the_change_stays_inside_calendar() -> None:
    css = _css()
    for foreign in (".library-view", ".claw-workspace", ".main-panel::before", ".topbar"):
        assert foreign not in css, f"calendar.css must not reach into {foreign}"


def test_the_hidden_field_and_sidebar_contracts_survive() -> None:
    css = _css()
    # The class rule sets `display`, so the explicit [hidden] override must stay
    # (date-only / all-day hide the time-zone, start and end fields).
    assert re.search(r"\.calendar-record-field\[hidden\]\s*\{[^}]*display:\s*none", css)
    # #2834 sidebar budget: the nav entry's 40px row is a separate contract.
    assert re.search(r"#calendarNavButton\s*\{[^}]*min-height:\s*40px", css)


def test_the_floored_rules_still_target_the_markup_they_own() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    band = html[html.index('id="calendarView"') : html.index('<section class="conversation"')]
    for selector in ("calendarRefresh", "calendarTodayTab", "calendarRecordDate",
                     "calendarRecordTitle", "calendarAppointmentType"):
        assert selector in band, f"{selector} must live inside #calendarView"
