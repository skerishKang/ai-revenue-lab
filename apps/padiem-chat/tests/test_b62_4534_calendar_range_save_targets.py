"""#4534 — the Calendar period and save controls must expose a >=44x44 hit area.

Follow-up to #4515 (merged as #4532), which floored the refresh control, the
category tabs and the record/event inputs. A real-browser probe at exact main
`8497ad0` reproduced the remaining small targets:

* period previous/next arrows 35 x 34.8 CSS px,
* period "today" 44.73 x 34.8,
* record/appointment save 78.45 x 36.8.

`calendar.css` carries the same additive 44px floor used by #4515, and these
guards keep it honest: they bind the floor, not the arithmetic, and fail if the
glyph is inflated to fake a bigger target, if the non-interactive period *label*
is floored too, or if #4515 / #4501 / the #2834 sidebar contract regress.

Measured after the change (12 combinations: 390/920/1280/1440 x glass/light/dark):
arrows 44x44, today 44.73x44, save 78.45x44, 8px neighbour gaps, zero overlap and
zero page horizontal scroll. `#calendarNavButton` stays at its 40px #2834 value.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "static"
CALENDAR_CSS = STATIC / "calendar.css"

RANGE_BUTTON = r"\.calendar-range-button\s*\{"
RANGE_SHARED = r"\.calendar-range-button,\s*\.calendar-range-label\s*\{"
RANGE_LABEL = r"\.calendar-range-label\s*\{"
SUBMIT = r"\.calendar-record-submit\s*\{"
REFRESH = r"\.calendar-refresh-button\s*\{"
TAB = r"\.calendar-tab\s*\{"
RECORD_FIELDS = r"\.calendar-record-field input,\s*\.calendar-record-field textarea\s*\{"
RECORD_SELECT = r"\.calendar-record-field select\s*\{"
CALENDAR_VIEW = r"\.calendar-view\s*\{"


def _css(path: Path = CALENDAR_CSS) -> str:
    """CSS with comments removed, so prose cannot satisfy a declaration guard."""
    return re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.DOTALL)


def _rule(css: str, header: str) -> str:
    match = re.search(header, css)
    assert match is not None, f"rule not found: {header}"
    open_brace = css.index("{", match.start())
    return css[open_brace + 1 : css.index("}", open_brace)]


def _declares(body: str, declaration: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(declaration)}(?![\w-])", body) is not None


# --- the fix ------------------------------------------------------------------


def test_period_arrows_meet_the_44px_floor() -> None:
    body = _rule(_css(), RANGE_BUTTON)
    assert _declares(body, "min-width: 44px"), "the arrows measured 35px wide"
    assert _declares(body, "min-height: 44px"), "the arrows measured 34.8px tall"
    # The glyph must be centred inside the grown box, not pushed to a corner.
    assert _declares(body, "display: inline-flex")
    assert _declares(body, "align-items: center")
    assert _declares(body, "justify-content: center")


def test_save_buttons_meet_the_44px_floor() -> None:
    body = _rule(_css(), SUBMIT)
    assert _declares(body, "min-width: 44px")
    assert _declares(body, "min-height: 44px"), "the save buttons measured 36.8px tall"


def _all_rules(css: str, header: str) -> list[str]:
    """Bodies of every rule whose header matches `header`.

    `.calendar-range-label {` also appears inside the shared
    `.calendar-range-button, .calendar-range-label` header, so a single-match
    helper cannot tell the shared rule from the label's own rule.
    """
    bodies = []
    for match in re.finditer(header, css):
        open_brace = css.index("{", match.start())
        bodies.append(css[open_brace + 1 : css.index("}", open_brace)])
    return bodies


def test_the_period_label_is_not_floored() -> None:
    # The label shares the base rule with the buttons but is not interactive
    # (`cursor: default`, `min-width: 190px`). Flooring it would change a static
    # read-out's geometry, so the floor must live on the button rule alone.
    css = _css()
    shared = _rule(css, RANGE_SHARED)
    assert "min-height" not in shared and "min-width" not in shared
    label_rules = _all_rules(css, RANGE_LABEL)
    assert any(_declares(b, "min-width: 190px") for b in label_rules)
    assert any(_declares(b, "cursor: default") for b in label_rules)
    assert all("44px" not in b for b in label_rules), "the static period label must not be floored"


# --- the anti-patterns this fix must not turn into ---------------------------


@pytest.mark.parametrize(
    ("header", "declaration"),
    [
        # The range button's type size lives in the rule it shares with the label.
        (RANGE_SHARED, "font-size: 13px"),
        (SUBMIT, "font-size: 13px"),
    ],
)
def test_the_floor_grows_the_hit_area_not_the_glyph(header: str, declaration: str) -> None:
    # "Fix it by making the text bigger" would satisfy a naive 44px check while
    # wrecking the type scale. The shipped 13px label must survive verbatim.
    assert _declares(_rule(_css(), header), declaration)


def test_the_shipped_padding_and_weight_are_preserved() -> None:
    assert _declares(_rule(_css(), RANGE_BUTTON), "padding: 6px 10px") or _declares(
        _rule(_css(), RANGE_SHARED), "padding: 6px 10px"
    )
    submit = _rule(_css(), SUBMIT)
    assert _declares(submit, "padding: 7px 14px")
    assert _declares(submit, "font-weight: 700")


@pytest.mark.parametrize("header", [RANGE_BUTTON, SUBMIT])
def test_no_fixed_height_or_scale_hack_caps_the_floor(header: str) -> None:
    body = _rule(_css(), header)
    # A fixed `height` would fight `min-height`, and a transform would fake a hit
    # area the browser does not route touches to.
    assert not re.search(r"(?<![\w-])height:\s*\d", body), "use min-height, not a fixed height"
    assert "transform:" not in body
    assert "scale(" not in body


def test_the_disabled_state_contract_survives() -> None:
    css = _css()
    assert _declares(_rule(css, r"\.calendar-range-button\[disabled\]\s*\{"), "cursor: not-allowed")
    assert _declares(_rule(css, r"\.calendar-record-submit\[disabled\]\s*\{"), "cursor: not-allowed")


# --- boundaries this slice must respect --------------------------------------


def test_the_4515_floors_are_preserved() -> None:
    css = _css()
    for header in (REFRESH, TAB):
        body = _rule(css, header)
        assert _declares(body, "min-width: 44px") and _declares(body, "min-height: 44px")
    assert _declares(_rule(css, RECORD_FIELDS), "min-height: 44px")
    assert _declares(_rule(css, RECORD_SELECT), "min-height: 44px")


def test_the_4501_stacking_fix_is_preserved() -> None:
    body = _rule(_css(), CALENDAR_VIEW)
    assert _declares(body, "position: relative")
    assert re.search(r"z-index:\s*2\s*;", body), "the #4501 lift must survive verbatim"
    # Exactly one z-index in the file: this slice adds geometry, not layers.
    assert _css().count("z-index:") == 2 and "z-index: 50;" in _css()


def test_the_2834_sidebar_contract_is_untouched() -> None:
    css = _css()
    nav = _rule(css, r"#calendarNavButton\s*\{")
    assert _declares(nav, "min-height: 40px"), "the sidebar row keeps its #2834 40px contract"
    assert "44px" not in nav, "this issue must not re-open the sidebar height contract"


def test_the_change_stays_inside_calendar() -> None:
    css = _css()
    for foreign in (".library-view", ".claw-workspace", ".main-panel::before", ".topbar"):
        assert foreign not in css, f"calendar.css must not reach into {foreign}"


def test_the_floored_rules_still_target_the_markup_they_own() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    band = html[html.index('id="calendarView"') : html.index('<section class="conversation"')]
    for selector in ("calendarPreviousRange", "calendarRangeToday", "calendarNextRange",
                     "calendarRecordSubmit", "calendarAppointmentSubmit"):
        assert selector in band, f"{selector} must live inside #calendarView"
