"""#2834 A3 — Native Calendar Today/Upcoming read-only UI contract tests.

Source-contract coverage (no browser required):
- index.html entry points: nav button, calendar view section, css/script wiring.
- calendar.js read-only semantics: two GET endpoints with explicit timezone,
  loading/empty/error/ready separation, retry, textContent-only rendering,
  no writes, no client-side item synthesis.
- locale.js ko/en keys for the calendar surface.
- calendar.css state gating.
- node -e behavioral checks for the exported pure helpers.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
INDEX_PATH = STATIC / "index.html"
CALENDAR_JS_PATH = STATIC / "calendar.js"
CALENDAR_CSS_PATH = STATIC / "calendar.css"
LOCALE_PATH = STATIC / "locale.js"
APP_PATH = STATIC / "app.js"

CALENDAR_LOCALE_KEYS = [
    "nav-calendar",
    "calendar-kicker",
    "calendar-title",
    "calendar-help",
    "calendar-refresh-aria",
    "calendar-tabs-aria",
    "calendar-today",
    "calendar-upcoming",
    "calendar-loading",
    "calendar-error",
    "calendar-empty-today",
    "calendar-empty-upcoming",
    "calendar-all-day",
    "calendar-item-work-log",
    "calendar-item-appointment",
    "calendar-item-task",
    "calendar-item-alert",
    "calendar-item-claw-run",
    "calendar-item-automation-run",
    "calendar-item-unknown",
    "calendar-item-untitled",
]

KNOWN_ITEM_TYPES = [
    "work_log",
    "appointment",
    "task",
    "alert",
    "claw_run",
    "automation_run",
]


def test_calendar_entry_points_are_wired_in_index_html() -> None:
    html = INDEX_PATH.read_text(encoding="utf-8")
    assert 'href="./calendar.css"' in html
    assert html.index('href="./calendar.css"') < html.index("<style>[hidden]")
    assert 'id="clawNavButton"' in html
    assert 'id="calendarNavButton"' in html
    assert html.index('id="clawNavButton"') < html.index('id="calendarNavButton"')
    assert 'data-locale-key="nav-calendar"' in html
    assert 'id="calendarView"' in html
    assert html.index('id="calendarView"') < html.index('<section class="conversation"')
    assert 'data-locale-key="calendar-today"' in html
    assert 'data-locale-key="calendar-upcoming"' in html
    assert 'data-locale-key="calendar-loading"' in html
    assert 'data-locale-key="calendar-error"' in html
    assert 'id="calendarRetry"' in html
    assert 'data-locale-key="retry"' in html
    assert html.index('src="./calendar.js"') < html.index('src="./app.js"')


def test_calendar_js_targets_both_existing_endpoints_with_explicit_timezone() -> None:
    source = CALENDAR_JS_PATH.read_text(encoding="utf-8")
    assert '"/api/calendar/today"' in source
    assert '"/api/calendar/upcoming"' in source
    assert "buildQuery" in source
    assert "timezone=" in source
    assert "browserTimezone" in source
    assert "Intl.DateTimeFormat().resolvedOptions().timeZone" in source
    # The server requires an explicit timezone; the client must not hardcode one.
    assert "Asia/Seoul" not in source
    assert "credentials: \"same-origin\"" in source
    assert 'cache: "no-store"' in source
    # Read-only: no request method option is set anywhere (defaults to GET only).
    assert "method:" not in source
    assert not re.search(r"\b(POST|PUT|PATCH|DELETE)\b", source)


def test_calendar_js_separates_loading_empty_error_ready_and_retry() -> None:
    source = CALENDAR_JS_PATH.read_text(encoding="utf-8")
    assert 'setStatus("loading")' in source
    assert 'setStatus("empty")' in source
    assert 'setStatus("error")' in source
    assert 'setStatus("ready")' in source
    assert 'document.getElementById("calendarRetry")' in source
    assert 'document.getElementById("calendarLoading")' in source
    assert 'document.getElementById("calendarEmpty")' in source
    assert 'document.getElementById("calendarErrorBox")' in source
    # Retry re-runs the same read-only load; empty is never reused as error.
    assert 'retry.addEventListener("click", () => load())' in source
    assert "requestToken" in source
    # The failed-response path and the zero-item path are distinct code paths.
    assert re.search(r"function showError\(\) \{\s*lastItems = null;\s*list\.replaceChildren\(\);\s*setStatus\(\"error\"\);", source)
    assert re.search(r"if \(!response\.ok \|\| !items\) \{\s*showError\(\);\s*return;", source)
    assert re.search(r"if \(items\.length === 0\) \{\s*list\.replaceChildren\(\);\s*setStatus\(\"empty\"\);\s*return;", source)


def test_calendar_js_renders_six_known_item_types_fail_soft() -> None:
    source = CALENDAR_JS_PATH.read_text(encoding="utf-8")
    for item_type in KNOWN_ITEM_TYPES:
        assert f'"{item_type}"' in source
        assert f"calendar-item-{item_type.replace('_', '-')}" in source
    assert "KNOWN_ITEM_TYPES" in source
    assert "isKnownItemType" in source
    assert '"calendar-item-unknown"' in source
    assert '"calendar-item-untitled"' in source
    # No client-side item synthesis signal.
    assert "item_type:" not in source


def test_calendar_js_is_text_only_and_never_creates_markup_or_links() -> None:
    source = CALENDAR_JS_PATH.read_text(encoding="utf-8")
    assert "textContent" in source
    assert "createElement" in source
    assert "innerHTML" not in source
    assert "insertAdjacentHTML" not in source
    assert "outerHTML" not in source
    assert "javascript:" not in source
    assert 'createElement("a")' not in source
    assert "href" not in source


def test_calendar_js_has_no_storage_no_artifact_dependency_and_frozen_export() -> None:
    source = CALENDAR_JS_PATH.read_text(encoding="utf-8")
    assert "localStorage" not in source
    assert "sessionStorage" not in source
    assert "artifact" not in source.lower()
    assert "window.PadiemCalendarUI" in source
    assert "Object.freeze" in source
    # Node environments (tests) must be able to import the pure helpers only.
    assert 'typeof document === "undefined"' in source


def test_locale_js_defines_calendar_keys_for_ko_and_en() -> None:
    source = LOCALE_PATH.read_text(encoding="utf-8")
    for key in CALENDAR_LOCALE_KEYS:
        assert source.count(f'"{key}":') >= 2, f"missing locale key: {key}"
    assert '"retry":' in source


def test_calendar_css_gates_the_view_on_calendar_state_only() -> None:
    css = CALENDAR_CSS_PATH.read_text(encoding="utf-8")
    assert '.app-shell[data-state="calendar"] .calendar-view' in css
    assert '.app-shell:not([data-state="calendar"]) .calendar-view' in css
    assert "display: none !important" in css
    assert '.app-shell[data-state="calendar"] .conversation' in css
    assert '.app-shell[data-state="calendar"] .composer-wrap' in css
    assert '#calendarNavButton[aria-current="page"]' in css


def test_calendar_ui_pure_helpers_behave_as_contracted() -> None:
    script = f"""
    global.window = {{}};
    require({json.dumps(str(CALENDAR_JS_PATH))});
    const ui = window.PadiemCalendarUI;
    if (!ui) throw new Error("PadiemCalendarUI missing");
    process.stdout.write(JSON.stringify({{
      todayRoute: ui.routeFor("today"),
      upcomingRoute: ui.routeFor("upcoming"),
      fallbackRoute: ui.routeFor("nope"),
      query: ui.buildQuery("Europe/Berlin"),
      queryEscaped: ui.buildQuery("Some Zone"),
      knownWorkLog: ui.isKnownItemType("work_log"),
      knownAutomation: ui.isKnownItemType("automation_run"),
      unknownText: ui.isKnownItemType("nope"),
      unknownNumber: ui.isKnownItemType(6),
      typeKeyKnown: ui.itemTypeKey("claw_run"),
      typeKeyUnknown: ui.itemTypeKey("mystery"),
      knownTypesLength: ui.KNOWN_ITEM_TYPES.length,
      whenTimed: ui.formatWhen({{ date: "2026-09-22", start_at: "2026-09-22T01:00:00+00:00", end_at: "2026-09-22T02:00:00+00:00", timezone: "Europe/Berlin", all_day: false }}),
      whenNoZone: ui.formatWhen({{ date: "2026-09-22", start_at: "2026-09-22T01:00:00+00:00", end_at: null, timezone: null, all_day: false }}),
      whenAllDay: ui.formatWhen({{ date: "2026-09-22", start_at: null, end_at: null, timezone: "Europe/Berlin", all_day: true }}),
      whenNullItem: ui.formatWhen(null),
      whenBrokenTime: ui.formatWhen({{ date: "2026-09-22", start_at: "not-a-date", timezone: "Europe/Berlin", all_day: false }}),
    }}));
    """
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    data = json.loads(completed.stdout)
    assert data["todayRoute"] == "/api/calendar/today"
    assert data["upcomingRoute"] == "/api/calendar/upcoming"
    assert data["fallbackRoute"] == "/api/calendar/today"
    assert data["query"] == "?timezone=Europe%2FBerlin"
    assert data["queryEscaped"] == "?timezone=Some%20Zone"
    assert data["knownWorkLog"] is True
    assert data["knownAutomation"] is True
    assert data["unknownText"] is False
    assert data["unknownNumber"] is False
    assert data["typeKeyKnown"] == "calendar-item-claw-run"
    assert data["typeKeyUnknown"] == "calendar-item-unknown"
    assert data["knownTypesLength"] == 6
    # Timed items show the server date plus server-timezone clock times.
    assert data["whenTimed"].startswith("2026-09-22 ")
    assert "–" in data["whenTimed"]
    assert data["whenTimed"].count(":") >= 2
    # Without a server timezone (or for all-day items) only the date is shown.
    assert data["whenNoZone"] == "2026-09-22"
    assert data["whenAllDay"] == "2026-09-22"
    assert data["whenNullItem"] == ""
    assert data["whenBrokenTime"] == "2026-09-22"
