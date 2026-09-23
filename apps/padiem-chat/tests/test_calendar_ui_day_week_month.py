"""#2834 A6 - Day/Week/Month UI composition over the canonical range projection."""

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


def _source() -> str:
    return CALENDAR_JS_PATH.read_text(encoding="utf-8")


def test_existing_calendar_surface_exposes_all_range_tabs_and_navigation() -> None:
    html = INDEX_PATH.read_text(encoding="utf-8")
    for tab in ("today", "day", "week", "month", "upcoming"):
        assert f'data-calendar-tab="{tab}"' in html
    for element_id in (
        "calendarRangeNavigation",
        "calendarPreviousRange",
        "calendarRangeLabel",
        "calendarRangeToday",
        "calendarNextRange",
    ):
        assert f'id="{element_id}"' in html
    assert 'id="calendarPanel"' in html


def test_range_ui_reuses_the_existing_read_only_authority() -> None:
    source = _source()
    assert 'const ITEMS_ROUTE = "/api/calendar/items"' in source
    assert "buildItemsQuery" in source
    assert "start_date=" in source and "end_date=" in source
    assert 'credentials: "same-origin"' in source
    assert 'cache: "no-store"' in source
    assert source.count('method: "POST"') == 2
    assert not re.search(r"\b(PUT|PATCH|DELETE)\b", source)
    assert "workspace_id" not in source
    assert "owner_id" not in source
    assert "tenant_id" not in source
    assert "source_ref" not in source
    assert "innerHTML" not in source
    assert 'fetch(`${ITEMS_ROUTE}${buildItemsQuery' in source
    assert "isRenderableItem" in source


def test_range_ui_has_bounded_states_and_explicit_timezone() -> None:
    source = _source()
    for state in ('setStatus("loading")', 'setStatus("empty")', 'setStatus("error")', 'setStatus("ready")'):
        assert state in source
    assert "browserTimezone()" in source
    assert "localDateInZone(timezone)" in source
    assert 'if (!timezone)' in source
    for key in ("calendar-empty-day", "calendar-empty-week", "calendar-empty-month"):
        assert f'"{key}"' in source


def test_range_locale_and_responsive_controls_are_defined_in_both_languages() -> None:
    locale = LOCALE_PATH.read_text(encoding="utf-8")
    for key in (
        "calendar-day",
        "calendar-week",
        "calendar-month",
        "calendar-empty-day",
        "calendar-empty-week",
        "calendar-empty-month",
        "calendar-previous-aria",
        "calendar-next-aria",
    ):
        assert locale.count(f'"{key}":') >= 2
    css = CALENDAR_CSS_PATH.read_text(encoding="utf-8")
    assert ".calendar-range-navigation" in css
    assert ".calendar-range-button" in css
    assert "overflow-x: auto" in css


def test_range_helpers_use_plain_calendar_dates_and_are_dst_independent() -> None:
    script = f"""
    global.window = {{}};
    require({json.dumps(str(CALENDAR_JS_PATH))});
    const ui = window.PadiemCalendarUI;
    const result = {{
      day: ui.rangeForView("day", "2026-09-23"),
      week: ui.rangeForView("week", "2026-09-23"),
      weekBoundary: ui.rangeForView("week", "2027-01-01"),
      month: ui.rangeForView("month", "2028-02-29"),
      yearMonth: ui.rangeForView("month", "2026-12-31"),
      prevDay: ui.shiftRangeAnchor("day", "2026-03-08", -1),
      nextWeek: ui.shiftRangeAnchor("week", "2026-12-28", 1),
      prevMonth: ui.shiftRangeAnchor("month", "2028-03-31", -1),
      nextMonth: ui.shiftRangeAnchor("month", "2026-12-31", 1),
      query: ui.buildItemsQuery("2026-09-21", "2026-09-27", "America/New_York"),
      invalid: ui.rangeForView("week", "2026-02-30")
    }};
    process.stdout.write(JSON.stringify(result));
    """
    completed = subprocess.run(
        ["node", "-e", script], check=True, capture_output=True, text=True
    )
    result = json.loads(completed.stdout)
    assert result["day"] == {"start_date": "2026-09-23", "end_date": "2026-09-23"}
    assert result["week"] == {"start_date": "2026-09-21", "end_date": "2026-09-27"}
    assert result["weekBoundary"] == {"start_date": "2026-12-28", "end_date": "2027-01-03"}
    assert result["month"] == {"start_date": "2028-02-01", "end_date": "2028-02-29"}
    assert result["yearMonth"] == {"start_date": "2026-12-01", "end_date": "2026-12-31"}
    assert result["prevDay"] == "2026-03-07"
    assert result["nextWeek"] == "2027-01-04"
    assert result["prevMonth"] == "2028-02-29"
    assert result["nextMonth"] == "2027-01-31"
    assert result["query"] == (
        "?timezone=America%2FNew_York&start_date=2026-09-21&end_date=2026-09-27"
    )
    assert result["invalid"] is None


def test_range_read_is_get_only_and_registered_server_route_is_canonical() -> None:
    source = _source()
    routes = (ROOT / "app" / "app_factory.py").read_text(encoding="utf-8")
    contracts = (ROOT / "app" / "calendar_routes.py").read_text(encoding="utf-8")
    assert 'Route("/api/calendar/items", calendar_items, methods=["GET"])' in routes
    assert 'async def calendar_items' in contracts
    assert "start_date" in contracts and "end_date" in contracts
    range_block = source.split("if (isRangeTab(currentTab))", 1)[1].split("function selectTab", 1)[0]
    assert "method:" not in range_block
    assert 'credentials: "same-origin"' in range_block
    assert 'cache: "no-store"' in range_block


def test_real_calendar_module_drives_range_navigation_states_and_bounded_month_groups() -> None:
    harness = f"""
    const fs = require("fs");
    const vm = require("vm");
    const source = fs.readFileSync({json.dumps(str(CALENDAR_JS_PATH))}, "utf8");
    const index = fs.readFileSync({json.dumps(str(INDEX_PATH))}, "utf8");
    const ids = [];
    const tagRe = /<([a-zA-Z0-9-]+)([^>]*)>/g;
    let match;
    while ((match = tagRe.exec(index)) !== null) {{
      const found = /\\sid="([^"]+)"/.exec(match[2]);
      if (found && !ids.includes(found[1])) ids.push(found[1]);
    }}
    function makeEl(tag) {{
      const el = {{ tagName: tag, id: "", textContent: "", hidden: false, disabled: false,
        value: "", children: [], listeners: {{}}, dataset: {{}},
        classList: {{ add() {{}}, remove() {{}}, contains() {{ return false; }}, toggle() {{}} }} }};
      el.setAttribute = (key, value) => {{ el[key] = String(value); }};
      el.append = (...children) => children.forEach((child) => el.children.push(child));
      el.appendChild = (child) => {{ el.children.push(child); return child; }};
      el.replaceChildren = (...children) => {{ el.children = children.slice(); }};
      el.addEventListener = (name, fn) => {{ (el.listeners[name] ||= []).push(fn); }};
      el.click = () => (el.listeners.click || []).forEach((fn) => fn({{ target: el, preventDefault() {{}} }}));
      el.closest = () => el;
      return el;
    }}
    const byId = {{}};
    ids.forEach((id) => {{ byId[id] = makeEl("div"); byId[id].id = id; }});
    const shell = makeEl("div");
    shell.dataset.state = "home";
    byId.calendarTodayTab.dataset.calendarTab = "today";
    byId.calendarDayTab.dataset.calendarTab = "day";
    byId.calendarWeekTab.dataset.calendarTab = "week";
    byId.calendarMonthTab.dataset.calendarTab = "month";
    byId.calendarUpcomingTab.dataset.calendarTab = "upcoming";
    const requests = [];
    let rangeMode = "items";
    function response(status, body) {{ return {{ ok: status >= 200 && status < 300, status, json: async () => body }}; }}
    async function fetchImpl(url, options) {{
      options = options || {{}};
      requests.push({{ url: String(url), method: options.method || "GET", credentials: options.credentials, cache: options.cache }});
      if (String(url).startsWith("/api/calendar/today")) return response(200, {{ ok: true, projection: {{ items: [] }} }});
      if (!String(url).startsWith("/api/calendar/items")) return response(404, {{}});
      if (rangeMode === "unauthorized") return response(401, {{ ok: false }});
      if (rangeMode === "unavailable") return response(503, {{ ok: false }});
      if (String(url).includes("start_date=2026-09-01")) return response(200, {{ ok: true, projection: {{ items: [
        {{ date: "2026-09-01", item_type: "task", title: "First day", summary: null, all_day: true, source_type: "task" }},
        {{ date: "2026-09-30", item_type: "appointment", title: "<safe text>", summary: null, all_day: true, source_type: "native_appointment" }},
        {{ date: "not-a-date", item_type: "task", title: "must be ignored" }}
      ] }} }});
      return response(200, {{ ok: true, projection: {{ items: [
        {{ date: "2026-09-23", item_type: "work_log", title: "Range item", summary: null, all_day: false, source_type: "native_work_log" }}
      ] }} }});
    }}
    const document = {{ readyState: "complete", getElementById: (id) => byId[id] || null,
      querySelector: (selector) => selector === ".app-shell" ? shell : null,
      createElement: (tag) => makeEl(tag), addEventListener() {{}} }};
    const sandbox = {{ document, fetch: fetchImpl, Intl, Date, JSON, Number, Object, String, Array,
      RegExp, Promise, setTimeout, clearTimeout, console, MutationObserver: undefined }};
    sandbox.window = sandbox;
    sandbox.window.addEventListener = () => {{}};
    sandbox.__padiemLocale = {{ text: (key) => key }};
    vm.createContext(sandbox);
    vm.runInContext(source, sandbox);
    const wait = () => new Promise((resolve) => setTimeout(resolve, 5));
    const textOf = (node) => (node.textContent || "") + (node.children || []).map(textOf).join("");
    (async () => {{
      byId.calendarNavButton.click();
      await wait();
      const todayLoads = requests.length === 1 && requests[0].method === "GET" && requests[0].url.includes("/api/calendar/today?timezone=");
      const tabs = byId.calendarTabs;
      tabs.listeners.click[0]({{ target: byId.calendarDayTab }});
      const loadingVisible = byId.calendarLoading.hidden === false;
      await wait();
      const dayLoad = requests[1];
      const dayReady = dayLoad && dayLoad.method === "GET" && dayLoad.url.includes("/api/calendar/items") && dayLoad.url.includes("start_date=") && dayLoad.url.includes("end_date=") && dayLoad.credentials === "same-origin" && dayLoad.cache === "no-store";
      byId.calendarPreviousRange.click();
      await wait();
      const previousLoad = requests[2] && requests[2].url;
      rangeMode = "unauthorized";
      tabs.listeners.click[0]({{ target: byId.calendarWeekTab }});
      await wait();
      const unauthorized = byId.calendarErrorBox.hidden === false && byId.calendarList.hidden === true;
      rangeMode = "unavailable";
      tabs.listeners.click[0]({{ target: byId.calendarDayTab }});
      await wait();
      const unavailable = byId.calendarErrorBox.hidden === false;
      rangeMode = "items";
      tabs.listeners.click[0]({{ target: byId.calendarMonthTab }});
      await wait();
      const groups = byId.calendarList.children;
      const monthGrouped = groups.length === 2 && textOf(groups[0]).includes("First day") && textOf(groups[1]).includes("<safe text>") && !textOf(byId.calendarList).includes("must be ignored");
      process.stdout.write(JSON.stringify({{ todayLoads, loadingVisible, dayReady, previousLoad, unauthorized, unavailable, monthGrouped }}));
    }})();
    """
    completed = subprocess.run(["node", "-e", harness], check=True, capture_output=True, text=True)
    result = json.loads(completed.stdout)
    assert result["todayLoads"] is True
    assert result["loadingVisible"] is True
    assert result["dayReady"] is True
    assert "/api/calendar/items" in result["previousLoad"]
    assert result["unauthorized"] is True
    assert result["unavailable"] is True
    assert result["monthGrouped"] is True
