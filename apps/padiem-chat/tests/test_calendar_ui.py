"""#2834 A3/A4 — Native Calendar Today/Upcoming UI contract tests.

The A3 slice shipped a read-only surface. A4 wires the already-registered native
work-log write authority into the same surface, so the contract is now:

* the READ path is still exactly the two GET endpoints with an explicit timezone;
* there is exactly ONE write, POST /api/calendar/work-logs, and no other
  method or endpoint is ever used (see test_calendar_ui_work_log_create.py);
* the surface keeps textContent-only rendering, no client-side item synthesis
  and no owner/workspace construction.

Source-contract coverage (no browser required):
- index.html entry points: nav button, calendar view section, css/script wiring.
- calendar.js semantics: two GET read endpoints with explicit timezone,
  loading/empty/error/ready separation, retry, textContent-only rendering,
  no client-side item synthesis, one bounded write path.
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
    "calendar-detail-open",
    "calendar-detail-close",
    "calendar-detail-loading",
    "calendar-detail-error",
    "calendar-detail-retry",
    "calendar-detail-source",
    "calendar-detail-created",
    "calendar-detail-updated",
    "calendar-detail-summary",
    "calendar-item-date",
    "calendar-detail-links",
    "calendar-detail-link-session",
    "calendar-detail-link-task",
    "calendar-detail-link-artifact",
    "calendar-detail-link-run",
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
    # The READ path sets no request method at all (it defaults to GET).
    read_block = source.split("async function load() {", 1)[1].split("function selectTab(", 1)[0]
    assert "method:" not in read_block
    assert 'fetch(`${routeFor(currentTab)}${buildQuery(timezone)}`' in read_block
    # #2834 A4/A5: exactly two write methods exist in the whole module, and both
    # are pre-registered native authorities (work-log POST, appointment POST).
    # No PUT/PATCH/DELETE is ever used, and no third write path is introduced.
    assert source.count('method: "POST"') == 2
    assert '"/api/calendar/work-logs"' in source
    assert '"/api/calendar/appointments"' in source
    assert not re.search(r"\b(PUT|PATCH|DELETE)\b", source)


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


def test_calendar_js_is_text_only_and_never_creates_anchors_or_html() -> None:
    source = CALENDAR_JS_PATH.read_text(encoding="utf-8")
    assert "textContent" in source
    assert "createElement" in source
    assert "innerHTML" not in source
    assert "insertAdjacentHTML" not in source
    assert "outerHTML" not in source
    assert "javascript:" not in source
    assert 'createElement("a")' not in source
    assert "href" not in source


def test_calendar_js_has_no_storage_and_frozen_export() -> None:
    source = CALENDAR_JS_PATH.read_text(encoding="utf-8")
    assert "localStorage" not in source
    assert "sessionStorage" not in source
    assert "window.PadiemCalendarUI" in source
    assert "Object.freeze" in source
    # Node environments (tests) must be able to import the pure helpers only.
    assert 'typeof document === "undefined"' in source


def test_calendar_js_renders_source_type_as_plain_text_only() -> None:
    source = CALENDAR_JS_PATH.read_text(encoding="utf-8")
    # source_type is a public bounded field and must be rendered; the internal
    # reference field is never read and never rendered.
    assert "sourceTypeText" in source
    assert '"calendar-item-source"' in source
    assert re.search(
        r'const sourceText = sourceTypeText\(item\);\s*if \(sourceText\) head\.append\(el\("span", "calendar-item-source", sourceText\)\);',
        source,
    )
    assert "source_ref" not in source
    assert "sourceRef" not in source
    # Missing or malformed source_type must not break the row: the chip is only
    # appended when the guard holds, and the row itself has no throwing branch.
    assert "if (sourceText) head.append(" in source
    assert 'return typeof item.source_type === "string" ? item.source_type.trim() : "";' in source
    # No markup sink can interpret a hostile source_type value.
    for sink in ("innerHTML", "insertAdjacentHTML", "outerHTML", "DOMParser", "document.write", "eval("):
        assert sink not in source


def test_calendar_item_detail_is_read_only_and_link_backs_are_server_validated() -> None:
    source = CALENDAR_JS_PATH.read_text(encoding="utf-8")
    assert 'const ITEM_DETAIL_ROUTE = "/api/calendar/items"' in source
    assert "buildItemDetailRoute" in source
    assert "isRenderableDetail" in source
    assert "isRenderableLinkBack" in source
    assert 'padiem:calendar-open-link' in source
    assert "link_backs" in source
    assert "target_id" in source
    assert "dispatchCalendarLink" in source
    detail_block = source.split("async function loadItemDetail(", 1)[1].split("function buildRow(", 1)[0]
    assert "method:" not in detail_block
    assert 'credentials: "same-origin"' in detail_block
    assert 'cache: "no-store"' in detail_block
    assert "createElement(\"a\")" not in source
    assert "href" not in source
    assert source.count('method: "POST"') == 2
    for kind in ("claw_session", "task", "artifact", "run"):
        assert f'"{kind}"' in source
    app = APP_PATH.read_text(encoding="utf-8")
    assert 'window.addEventListener("padiem:calendar-open-link"' in app
    assert 'openClawInboxTarget("tasks", targetId)' in app
    assert "openClawRunTarget(targetId)" in app
    assert "downloadClawArtifact(targetId" in app


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


def test_calendar_css_reclaims_sidebar_space_for_the_new_entry() -> None:
    css = CALENDAR_CSS_PATH.read_text(encoding="utf-8")
    # The nav entry adds one sidebar row; the css must compensate so the
    # recent list sections stay clickable (B62 browser QA regression guard).
    assert ".sidebar {" in css
    assert "gap: 12px" in css
    assert "padding-top: 14px" in css
    assert 'html[data-theme="padiem-glass"] .sidebar {' in css
    assert ".side-nav {" in css
    assert "gap: 3px" in css
    assert "min-height: 40px" in css


def test_calendar_ui_pure_helpers_behave_as_contracted() -> None:
    script = f"""
    global.window = {{}};
    require({json.dumps(str(CALENDAR_JS_PATH))});
    const ui = window.PadiemCalendarUI;
    if (!ui) throw new Error("PadiemCalendarUI missing");
     const sessionId = "chat_" + "a".repeat(32);
     const artifactId = "doc_" + "b".repeat(32);
     const detailPayload = {{ ok: true, detail: {{ item: {{ calendar_item_id: "item_task_task_1", item_type: "task", title: "Task", date: "2026-09-20" }}, link_backs: [{{ kind: "task", target_id: "task_1" }}] }} }};
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
       sourceKnown: ui.sourceTypeText({{ source_type: "native_work_log" }}),
       sourcePadded: ui.sourceTypeText({{ source_type: "  claw_run  " }}),
       sourceMarkupShaped: ui.sourceTypeText({{ source_type: "<img src=x onerror=alert(1)>" }}),
       sourceMissing: ui.sourceTypeText({{}}),
       sourceNumeric: ui.sourceTypeText({{ source_type: 5 }}),
       sourceNullItem: ui.sourceTypeText(null),
       sourceIsFunction: typeof ui.sourceTypeText,
       detailRoute: ui.buildItemDetailRoute("item_task_task_1", "Asia/Seoul"),
       detailRouteBadId: ui.buildItemDetailRoute("../secret", "Asia/Seoul"),
       detailRouteBadZone: ui.buildItemDetailRoute("item_task_task_1", ""),
       linkSession: ui.isRenderableLinkBack({{ kind: "claw_session", target_id: sessionId }}),
       linkArtifact: ui.isRenderableLinkBack({{ kind: "artifact", target_id: artifactId }}),
       linkExternal: ui.isRenderableLinkBack({{ kind: "artifact", target_id: "https://example.test/a" }}),
       detailRenderable: ui.isRenderableDetail(detailPayload, "item_task_task_1"),
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
    assert data["sourceIsFunction"] == "function"
    assert data["sourceKnown"] == "native_work_log"
    assert data["sourcePadded"] == "claw_run"
    # A hostile value stays a plain string (data), never parsed as markup.
    assert data["sourceMarkupShaped"] == "<img src=x onerror=alert(1)>"
    assert data["sourceMissing"] == ""
    assert data["sourceNumeric"] == ""
    assert data["sourceNullItem"] == ""
    assert data["detailRoute"] == "/api/calendar/items/item_task_task_1?timezone=Asia%2FSeoul"
    assert data["detailRouteBadId"] == ""
    assert data["detailRouteBadZone"] == ""
    assert data["linkSession"] is True
    assert data["linkArtifact"] is True
    assert data["linkExternal"] is False
    assert data["detailRenderable"] is True
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
