"""#4545 — the Claw automation controls must expose a >=44x44 hit area.

A real-browser probe at exact main `17d90e9` (24 combinations: 390/920/1280/1440
x glass/light/dark x ko/en, every reachable control measured through the app's
own render path) reproduced the remaining small targets on the Automation
surface:

* create disclosure `<summary>` (the entry point to the whole create form)
  20.8px tall in **every** theme,
* create/edit form inputs 40px tall under **glass** (the shared calendar.css
  floor already made the identical control 44px in light/dark),
* rule pause/resume toggle and edit buttons 40px tall under **glass** (the
  shared claw-workspace.css floor already made them 44x44 elsewhere).

`claw-focus-layout.css` — and only its Automation area — now carries the same
additive 44px floor. These guards bind the floor, not the arithmetic: they fail
if the glyph is inflated to fake a bigger target, if a static label is floored
too, if the theme-independent floor is re-gated behind glass, if the shared
Calendar/Claw contracts regress, or if the floor leaks outside `#clawAutomation`.

Measured after the change: every reachable control >=44x44 in 24/24
combinations, zero neighbour overlap, zero page horizontal scroll, and the
Enter/Space disclosure, edit-cancel focus return, rule-toggle round-trip and
daypart/interval/cron reveal parity all unchanged.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "static"
FOCUS_CSS = STATIC / "claw-focus-layout.css"
WORKSPACE_CSS = STATIC / "claw-workspace.css"
CALENDAR_CSS = STATIC / "calendar.css"

# The Automation block of claw-focus-layout.css is glass-gated; the disclosure
# floor is deliberately not (the 20.8px box was theme-independent).
GLASS_SUMMARY = 'html[data-theme="padiem-glass"] .app-shell[data-state="claw"] #clawAutomation .calendar-record-summary {'
FLOOR_SUMMARY = '\n.app-shell[data-state="claw"] #clawAutomation .calendar-record-summary {'
GLASS_INPUTS = 'html[data-theme="padiem-glass"] .app-shell[data-state="claw"] #clawAutomation .calendar-record-field :is(input, textarea, select) {'
GLASS_TOGGLE = 'html[data-theme="padiem-glass"] .app-shell[data-state="claw"] #clawAutomation :is(.claw-automation-rule-toggle, .claw-automation-rule-edit) {'
GLASS_RETRY = 'html[data-theme="padiem-glass"] .app-shell[data-state="claw"] #clawAutomation :is(.claw-inbox-retry, .claw-inbox-status-action) {'
GLASS_SUBMIT = 'html[data-theme="padiem-glass"] .app-shell[data-state="claw"] #clawAutomation .calendar-record-submit {'
GLASS_CANCEL = 'html[data-theme="padiem-glass"] .app-shell[data-state="claw"] #clawAutomation .calendar-record-cancel {'


def _css(path: Path) -> str:
    """CSS with comments removed, so prose cannot satisfy a declaration guard."""
    return re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.DOTALL)


def _rule(css: str, header: str) -> str:
    match = re.search(re.escape(header), css)
    assert match is not None, f"rule not found: {header}"
    open_brace = css.index("{", match.start())
    return css[open_brace + 1 : css.index("}", open_brace)]


def _declares(body: str, declaration: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(declaration)}(?![\w-])", body) is not None


# --- the fix ------------------------------------------------------------------


def test_the_create_disclosure_meets_the_44px_floor() -> None:
    body = _rule(_css(FOCUS_CSS), FLOOR_SUMMARY)
    assert _declares(body, "min-height: 44px"), "the summary measured 20.8px tall"
    # The box is the only thing that grows: with border-box the floor lands at
    # exactly 44px regardless of padding, so the label keeps its natural size.
    assert _declares(body, "box-sizing: border-box")
    assert not re.search(r"(?<![\w-])height:\s*\d", body), "use min-height, not a fixed height"


def test_the_glass_form_fields_meet_the_44px_floor() -> None:
    body = _rule(_css(FOCUS_CSS), GLASS_INPUTS)
    assert _declares(body, "min-height: 44px"), "the glass inputs measured 40px tall"
    assert "40px" not in body, "the old 40px floor must not survive anywhere in the rule"


def test_the_glass_rule_buttons_meet_the_44px_floor() -> None:
    body = _rule(_css(FOCUS_CSS), GLASS_TOGGLE)
    assert _declares(body, "min-height: 44px"), "the toggle/edit buttons measured 40px tall"
    assert "40px" not in body


# --- the anti-patterns this fix must not turn into ----------------------------


@pytest.mark.parametrize(
    ("header", "declaration"),
    [
        (GLASS_SUMMARY, "font-size: 13px"),
        (GLASS_INPUTS, "font-size: 13px"),
        (GLASS_TOGGLE, "font-size: 12px"),
        (GLASS_TOGGLE, "font-weight: 650"),
    ],
)
def test_the_floor_grows_the_hit_area_not_the_glyph(header: str, declaration: str) -> None:
    # "Fix it by making the text bigger" would satisfy a naive 44px check while
    # wrecking the type scale. The shipped label sizes must survive verbatim.
    assert _declares(_rule(_css(FOCUS_CSS), header), declaration)


def test_the_shipped_padding_is_preserved() -> None:
    assert _declares(_rule(_css(FOCUS_CSS), GLASS_INPUTS), "padding: 8px 11px")
    assert _declares(_rule(_css(FOCUS_CSS), GLASS_TOGGLE), "padding: 0 14px")


def test_the_disclosure_floor_does_not_restyle_the_label() -> None:
    body = _rule(_css(FOCUS_CSS), FLOOR_SUMMARY)
    # Colour, type size and weight belong to the glass rule above; a geometry
    # floor must not smuggle a visual restyle into every theme.
    for visual in ("font-size", "font-weight", "color", "background", "cursor"):
        assert not _declares(body, visual + ":"), f"the floor rule must not declare {visual}"


@pytest.mark.parametrize("header", [FLOOR_SUMMARY, GLASS_INPUTS, GLASS_TOGGLE])
def test_no_transform_hack_fakes_a_hit_area(header: str) -> None:
    body = _rule(_css(FOCUS_CSS), header)
    assert "transform:" not in body
    assert "scale(" not in body


# --- boundaries this slice must respect ---------------------------------------


def test_the_disclosure_floor_is_theme_independent() -> None:
    # The 20.8px box reproduced in light and dark as well; gating the floor
    # behind glass would leave two of the three themes broken.
    body = _rule(_css(FOCUS_CSS), FLOOR_SUMMARY)
    assert "data-theme" not in FLOOR_SUMMARY
    assert "data-theme" not in body


def test_the_visual_rules_stay_glass_gated() -> None:
    css = _css(FOCUS_CSS)
    for header in (GLASS_INPUTS, GLASS_TOGGLE, GLASS_SUMMARY):
        assert header.startswith('html[data-theme="padiem-glass"]')


def test_every_summary_rule_stays_inside_the_automation_panel() -> None:
    css = _css(FOCUS_CSS)
    for line in css.splitlines():
        if ".calendar-record-summary" in line:
            assert "#clawAutomation" in line, "a summary rule escaped the Automation panel"
    # ...and no bare global `.calendar-record-summary {` floor can appear.
    assert not re.search(r"(?m)^\s*\.calendar-record-summary\s*\{", css)


def test_the_floor_does_not_reach_other_claw_panels() -> None:
    css_all = _css(FOCUS_CSS)
    css = "\n".join(_rule(css_all, header) for header in (FLOOR_SUMMARY, GLASS_SUMMARY, GLASS_INPUTS, GLASS_TOGGLE))
    for foreign in ("#clawInbox", "#clawManualForm", "#clawRunHistory", "#clawPcEnrollment", "#calendarView"):
        assert foreign not in css, f"the Automation slice must not reach into {foreign}"


def test_the_mobile_media_query_cannot_cap_the_floor() -> None:
    css = _css(FOCUS_CSS)
    # The file has several 920px blocks; the Automation one is the last and the
    # only one that reflows #clawAutomation.
    start = css.rindex("@media (max-width: 920px)")
    media = css[start : css.index("\n}\n", start) + 2]
    assert "#clawAutomation" in media
    assert "width: 100%" in media, "the mobile full-width behaviour must survive"
    assert not re.search(r"(?<![\w-])min-height:", media), "a media query must not re-floor the controls"
    assert not re.search(r"(?<![\w-])height:\s*\d", media)


# --- contracts this slice must preserve ---------------------------------------


def test_the_shared_workspace_button_contracts_survive() -> None:
    css = _css(WORKSPACE_CSS)
    for header in (".claw-automation-rule-toggle {", ".claw-automation-rule-edit {"):
        body = _rule(css, header)
        assert _declares(body, "min-height: 44px")
        assert _declares(body, "min-width: 44px")
    retry = _rule(css, ".claw-inbox-retry,")
    assert _declares(retry, "min-height: 44px")
    # The glass retry rule must keep deferring to that shared floor: adding a
    # smaller min-height here would win the cascade and shrink the button.
    assert "min-height" not in _rule(_css(FOCUS_CSS), GLASS_RETRY)


def test_the_glass_save_buttons_keep_their_44px_floor() -> None:
    css = _css(FOCUS_CSS)
    assert _declares(_rule(css, GLASS_SUBMIT), "min-height: 44px")
    assert _declares(_rule(css, GLASS_CANCEL), "min-height: 44px")


def test_the_calendar_hit_target_and_stacking_fixes_are_preserved() -> None:
    css = _css(CALENDAR_CSS)
    assert _declares(_rule(css, ".calendar-record-field input,"), "min-height: 44px")
    assert _declares(_rule(css, ".calendar-record-field select {"), "min-height: 44px")
    assert _declares(_rule(css, ".calendar-refresh-button {"), "min-height: 44px")
    assert _declares(_rule(css, ".calendar-tab {"), "min-height: 44px")
    assert _declares(_rule(css, ".calendar-range-button {"), "min-height: 44px")
    assert _declares(_rule(css, ".calendar-record-submit {"), "min-height: 44px")
    # #4501: the decoration lift survives verbatim, and this slice adds no layers.
    view = _rule(css, ".calendar-view {")
    assert _declares(view, "position: relative")
    assert re.search(r"z-index:\s*2\s*;", view)
    assert css.count("z-index:") == 2 and "z-index: 50;" in css
    # #2834: the sidebar row keeps its 40px contract.
    nav = _rule(css, "#calendarNavButton {")
    assert _declares(nav, "min-height: 40px") and "44px" not in nav


def test_the_automation_markup_still_owns_its_controls() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    band = html[html.index('id="clawAutomation"') : html.index('<section class="calendar-view"')]
    for selector in (
        "clawAutomationCreateToggle",
        "clawAutomationCreateForm",
        "clawAutomationCreateCancel",
        "clawAutomationCreateSubmit",
        "clawAutomationEditForm",
        "clawAutomationEditCancel",
        "clawAutomationEditSubmit",
        "clawAutomationList",
    ):
        assert f'id="{selector}"' in band, f"{selector} must live inside #clawAutomation"
    # The create entry is the one disclosure on the surface; the edit form is a
    # plain <form>, so the summary floor family cannot reach it.
    assert band.count("<summary") == 1
    assert '<form class="calendar-record-form claw-automation-edit-form"' in band
    assert 'id="clawAutomationList" role="list"' in band


def test_the_stored_setting_is_still_never_presented_as_live_execution() -> None:
    # The floor must not drag the copy with it: the scheduler note and the
    # owner-gating wording are the #2833 hold, not decoration.
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    band = html[html.index('id="clawAutomation"') : html.index('<section class="calendar-view"')]
    assert 'id="clawAutomationSchedulerNote"' in band
    assert "자동 실행이 이미 활성화되어" in band
    assert 'id="clawAutomation"' in html
    assert 'id="clawAutomation" aria-labelledby' in html or 'aria-labelledby="clawAutomationTitle"' in html
    assert html.count('id="clawAutomation"') == 1
