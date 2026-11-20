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
import subprocess
from pathlib import Path

from _support.calendar_static import (  # noqa: E402
    app_js_source, calendar_rules, index_tags, locale_keys, nav_module_source, ui_facts,
)
from css_rules import declaration, find_rules_with_selector  # noqa: E402

CALENDAR_JS_PATH = Path(__file__).resolve().parents[1] / "static" / "calendar.js"

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
    tags = index_tags()
    attributes = [attrs for _tag, attrs in tags]
    ids = [attrs.get("id") for attrs in attributes]
    locale_keys_on_page = {attrs.get("data-locale-key") for attrs in attributes
                           if attrs.get("data-locale-key")}
    scripts = [attrs.get("src") for _tag, attrs in tags
               if attrs.get("src") and attrs["src"].endswith(".js")]
    styles = [attrs.get("href") for _tag, attrs in tags
              if attrs.get("href") and attrs["href"].endswith(".css")]
    assert "./calendar.css" in styles
    assert "clawNavButton" in ids and "calendarNavButton" in ids
    assert ids.index("clawNavButton") < ids.index("calendarNavButton")
    for key in ("nav-calendar", "calendar-today", "calendar-upcoming",
                "calendar-loading", "calendar-error", "retry"):
        assert key in locale_keys_on_page, key
    assert "calendarView" in ids
    assert "calendarRetry" in ids
    assert scripts.index("./calendar.js") < scripts.index("./app.js")


def test_calendar_js_targets_both_existing_endpoints_with_explicit_timezone() -> None:
    facts = ui_facts()
    assert set(facts["endpoints"]) >= {"/api/calendar/today", "/api/calendar/upcoming"}
    assert facts["build_query_present"] is True
    assert facts["query_timezone"] is True
    assert facts["browser_timezone"] is True and facts["intl_timezone"] is True
    assert facts["hardcoded_zone"] is False
    assert facts["fetch_credentials"] == ["same-origin"]
    assert facts["fetch_cache"] == ["no-store"]
    assert facts["read_has_method"] is False
    assert facts["fetch_route_template"] is True
    assert facts["write_method_calls"] == 2
    assert "/api/calendar/work-logs" in facts["endpoints"]
    assert "/api/calendar/appointments" in facts["endpoints"]
    assert facts["has_delete"] is True and facts["has_put"] is True
    assert facts["patch_present"] is False


def test_calendar_js_separates_loading_empty_error_ready_and_retry() -> None:
    facts = ui_facts()
    assert set(facts["statuses"]) == {"loading", "empty", "error", "ready"}
    for element in ("calendarRetry", "calendarLoading", "calendarEmpty", "calendarErrorBox"):
        assert element in facts["element_ids"], element
    assert facts["retry_listener"] is True
    assert facts["request_token"] is True
    assert facts["retry_on_auth_or_server"] is True
    assert set(facts["retry_wait_ms"]) == {"1500"}
    assert facts["empty_path_present"] is True


def test_calendar_js_renders_six_known_item_types_fail_soft() -> None:
    facts = ui_facts()
    assert facts["known_types"] == sorted(KNOWN_ITEM_TYPES)
    assert facts["known_type_constant"] is True and facts["known_type_helper"] is True
    assert "calendar-item-unknown" in facts["type_keys"]
    assert "calendar-item-untitled" in facts["type_keys"]
    assert facts["item_type_synthesis"] is False


def test_calendar_js_is_text_only_and_never_creates_anchors_or_html() -> None:
    facts = ui_facts()
    assert facts["dom_sinks"] == []
    assert facts["anchor_creation"] is False
    assert facts["href_usage"] is False


def test_calendar_js_has_no_storage_and_frozen_export() -> None:
    facts = ui_facts()
    assert facts["storage_apis"] == []
    assert facts["public_export"] is True and facts["frozen_export"] is True
    assert facts["node_guard"] is True


def test_calendar_js_renders_source_type_as_plain_text_only() -> None:
    facts = ui_facts()
    assert facts["source_type_text"] is True
    assert "calendar-item-source" in facts["type_keys"]
    assert facts["source_ref_fields"] == []
    assert facts["source_type_guard"] is True and facts["source_chip_guard"] is True
    assert facts["dom_sinks"] == []


def test_calendar_item_detail_is_read_only_and_link_backs_are_server_validated() -> None:
    facts = ui_facts()
    assert facts["item_detail_route"] == ["/api/calendar/items"]
    assert facts["detail_route_builder"] is True
    assert facts["detail_guard"] is True and facts["link_back_guard"] is True
    assert facts["open_link_event"] is True
    assert set(facts["link_back_fields"]) == {"link_backs", "target_id"}
    assert facts["detail_read_has_method"] is False
    assert facts["detail_credentials"] == ["same-origin"]
    assert facts["detail_cache"] == ["no-store"]
    assert facts["anchor_creation"] is False and facts["href_usage"] is False
    nav = app_js_source() + "\n" + nav_module_source()
    for needle in ("padiem:calendar-open-link", "openClawRunTarget(targetId)",
                   "downloadClawArtifact(targetId", "navModuleInstance.wireNavRouteListener();"):
        assert needle in nav, needle


def test_locale_js_defines_calendar_keys_for_ko_and_en() -> None:
    ko, en = locale_keys("ko"), locale_keys("en")
    for key in CALENDAR_LOCALE_KEYS:
        assert key in ko and key in en, key
    assert "retry" in ko and "retry" in en


def test_calendar_css_gates_the_view_on_calendar_state_only() -> None:
    rules = calendar_rules()
    selectors = [selector for rule in rules for selector in rule.selectors]
    for selector in ('.app-shell[data-state="calendar"] .calendar-view',
                     '.app-shell:not([data-state="calendar"]) .calendar-view',
                     '.app-shell[data-state="calendar"] .conversation',
                     '.app-shell[data-state="calendar"] .composer-wrap',
                     '#calendarNavButton[aria-current="page"]'):
        assert selector in selectors, selector
    values = [value for rule in rules for value in rule.declarations.values() if value]
    assert "none !important" in values


def test_calendar_css_reclaims_sidebar_space_for_the_new_entry() -> None:
    rules = calendar_rules()
    sidebar = [rule for rule in find_rules_with_selector(rules, ".sidebar")
               if rule.media is None]
    assert sidebar
    assert any(declaration(rule, "gap") == "12px" for rule in sidebar)
    assert any(declaration(rule, "padding-top") == "14px" for rule in sidebar)
    glass = [rule for rule in find_rules_with_selector(rules,
             'html[data-theme="padiem-glass"] .sidebar') if rule.media is None]
    assert glass
    side_nav = [rule for rule in find_rules_with_selector(rules, ".side-nav")
                if rule.media is None]
    assert any(declaration(rule, "gap") == "3px" for rule in side_nav)
    values = [value for rule in rules for value in rule.declarations.values() if value]
    assert "40px" in values


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
        text=True, encoding="utf-8",
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
