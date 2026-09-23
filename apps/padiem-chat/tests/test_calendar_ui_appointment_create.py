"""#2834 A5 — Native Padiem Calendar appointment create UI contract tests.

A4 wired the native work-record write authority into the product surface. A5 does
the same for the native appointment authority that already existed and was already
tested (POST /api/calendar/appointments, CalendarAppointment contract, CalendarStore
/ D1CalendarStore, workspace scope derived from the authenticated session):

    existing POST /api/calendar/appointments  ->  A5 form  ->  existing Today view

No endpoint, store, authority or reminder scheduler is added. The three supported
types are the contract's own three types, and a timed appointment is only ever
built from an explicit IANA zone into an offset-bearing ISO-8601 start, so a naive
datetime cannot be produced by this client at all.

Coverage:
- markup: type selector, bounded fields, explicit time-zone input, locale bindings.
- copy: the help text no longer denies appointment creation, and states what is
  still unsupported (edit/delete) plus the no-external-calendar / no-memory facts.
- source/authority: exactly two write POSTs (A4 work-log + A5 appointment), the
  existing registered route, payload keys that match the existing route contract,
  no scope construction, no PUT/PATCH/DELETE, no second authority.
- behavior: a Node DOM-stub harness executes the real static/calendar.js, drives
  the real submit path for date_only/all_day/timed, and asserts the exact request
  body plus every failure branch and every pre-request rejection.
"""

from __future__ import annotations

from datetime import date, timedelta
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from app.calendar_contracts import (
    AppointmentType,
    CalendarAppointment,
    CalendarContractError,
    EXTERNAL_CALENDAR_REQUIRED,
    MEMORY_AUTO_PROMOTION,
)

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
INDEX_PATH = STATIC / "index.html"
CALENDAR_JS_PATH = STATIC / "calendar.js"
CALENDAR_CSS_PATH = STATIC / "calendar.css"
LOCALE_PATH = STATIC / "locale.js"
APP_FACTORY_PATH = ROOT / "app" / "app_factory.py"
ROUTES_PATH = ROOT / "app" / "calendar_routes.py"

WORK_LOG_ROUTE = "/api/calendar/work-logs"
APPOINTMENT_ROUTE = "/api/calendar/appointments"

APPOINTMENT_LOCALE_KEYS = [
    "calendar-appointment-summary",
    "calendar-appointment-hint",
    "calendar-appointment-type-label",
    "calendar-appointment-type-date-only",
    "calendar-appointment-type-all-day",
    "calendar-appointment-type-timed",
    "calendar-appointment-title-label",
    "calendar-appointment-title-placeholder",
    "calendar-appointment-date-label",
    "calendar-appointment-timezone-label",
    "calendar-appointment-start-label",
    "calendar-appointment-end-label",
    "calendar-appointment-reminder-label",
    "calendar-appointment-description-label",
    "calendar-appointment-submit",
    "calendar-appointment-timezone-note",
    "calendar-appointment-created",
    "calendar-appointment-invalid",
    "calendar-appointment-unauthorized",
    "calendar-appointment-unavailable",
    "calendar-reminder-none",
    "calendar-reminder-10",
    "calendar-reminder-30",
    "calendar-reminder-60",
    "calendar-reminder-1440",
]

# The only keys this client can ever put on an appointment POST body. The route
# accepts exactly these (calendar_routes.calendar_appointments_create) and derives
# workspace_id / owner_id server-side.
CLIENT_PAYLOAD_KEYS = {
    "appointment_type",
    "title",
    "description",
    "date",
    "start_at",
    "end_at",
    "timezone",
    "reminder_minutes",
}

# Server bounds mirrored from calendar_contracts.
MAX_TITLE_CHARS = 200
MAX_DESCRIPTION_CHARS = 4_000
MAX_REMINDER_MINUTES = 40_320

OFFSET_SUFFIX = re.compile(r"(?:Z|[+-]\d{2}:\d{2})$")


def _index() -> str:
    return INDEX_PATH.read_text(encoding="utf-8")


def _source() -> str:
    return CALENDAR_JS_PATH.read_text(encoding="utf-8")


def _locale() -> str:
    return LOCALE_PATH.read_text(encoding="utf-8")


def _locale_value(key: str, lang: str) -> str | None:
    source = _locale()
    part = source.split("en: {", 1)[0] if lang == "ko" else source.split("en: {", 1)[1]
    match = re.search(rf'"{re.escape(key)}":\s*"((?:[^"\\]|\\.)*)"', part)
    return match.group(1).replace('\\"', '"') if match else None


def _appointment_form_markup() -> str:
    html = _index()
    start = html.index('id="calendarAppointment"')
    start = html.rindex("<details", 0, start)
    return html[start:].split("</details>", 1)[0] + "</details>"


def _appointment_type_values(markup: str) -> list[str]:
    block = markup.split('id="calendarAppointmentType"', 1)[1].split("</select>", 1)[0]
    return re.findall(r'<option value="([^"]+)"', block)


# ── markup ────────────────────────────────────────────────────────────────


def test_index_declares_the_appointment_form_with_bounded_fields() -> None:
    form = _appointment_form_markup()
    assert form.startswith("<details")
    for element_id in (
        "calendarAppointmentForm",
        "calendarAppointmentType",
        "calendarAppointmentTitle",
        "calendarAppointmentDate",
        "calendarAppointmentTimeZone",
        "calendarAppointmentStart",
        "calendarAppointmentEnd",
        "calendarAppointmentReminder",
        "calendarAppointmentDescription",
        "calendarAppointmentSubmit",
        "calendarAppointmentStatus",
    ):
        assert f'id="{element_id}"' in form, element_id
    assert 'type="submit"' in form
    assert f'maxlength="{MAX_TITLE_CHARS}"' in form
    assert f'maxlength="{MAX_DESCRIPTION_CHARS}"' in form
    assert 'type="date"' in form
    assert 'type="time"' in form
    assert "required" in form
    assert 'data-locale-placeholder="calendar-appointment-title-placeholder"' in form


def test_appointment_type_selector_offers_the_three_contract_types_only() -> None:
    values = _appointment_type_values(_appointment_form_markup())
    # The contract's own closed set, in the contract's own order, with the
    # least-specific type first so the default is the safest one.
    assert values == ["date_only", "all_day", "timed"]


def test_time_fields_are_bound_to_hideable_containers() -> None:
    form = _appointment_form_markup()
    # Each timed-only field sits in a labelled container the client toggles
    # (date-only/all-day must never show or send a start/end/time zone).
    for wrapper in (
        "calendarAppointmentTimeZoneField",
        "calendarAppointmentStartField",
        "calendarAppointmentEndField",
    ):
        assert f'id="{wrapper}"' in form, wrapper
        assert f'for="calendarAppointment' in form
    css = CALENDAR_CSS_PATH.read_text(encoding="utf-8")
    # The field class sets `display`, so [hidden] needs an explicit rule.
    assert ".calendar-record-field[hidden]" in css


def test_appointment_form_lives_inside_the_calendar_view_not_the_chat_shell() -> None:
    html = _index()
    view_start = html.index('id="calendarView"')
    view_end = html.index('<section class="conversation"')
    form_start = html.index('id="calendarAppointmentForm"')
    assert view_start < form_start < view_end
    # The A4 work-record form and the chat composer are untouched.
    assert html.count('id="calendarRecordForm"') == 1
    assert html.count('id="composerForm"') == 1


def test_appointment_status_region_is_an_announced_polite_status() -> None:
    form = _appointment_form_markup()
    before = form.split('id="calendarAppointmentStatus"', 1)[0]
    tag = before.rsplit("<p", 1)[1] + 'id="calendarAppointmentStatus"'
    tag += form.split('id="calendarAppointmentStatus"', 1)[1].split(">", 1)[0]
    assert 'role="status"' in tag
    assert 'aria-live="polite"' in tag
    assert "hidden" in tag


# ── copy truthfulness ────────────────────────────────────────────────────


def test_help_copy_no_longer_denies_appointment_creation() -> None:
    ko = _locale_value("calendar-help", "ko")
    en = _locale_value("calendar-help", "en")
    assert ko and en
    # The stale A3/A4 claim (appointment creation unsupported) must be gone...
    assert "일정(예약) 생성·수정은 아직 지원하지 않습니다" not in ko
    assert "creating or editing appointments is not supported" not in en
    # ...and what is still unsupported (edit/delete) must remain stated.
    assert "수정·삭제" in ko and "지원하지 않습니다" in ko
    assert "editing or deleting" in en and "not supported" in en
    fallback = re.search(r'data-locale-key="calendar-help">([^<]*)</p>', _index())
    assert fallback is not None and fallback.group(1) == ko


def test_hint_states_native_ownership_and_no_memory_promotion() -> None:
    ko = _locale_value("calendar-appointment-hint", "ko")
    en = _locale_value("calendar-appointment-hint", "en")
    assert ko and en
    # Native Padiem Calendar record: no external account is required.
    assert "Google" in ko and "Naver" in ko
    assert "Google" in en and "Naver" in en
    # And it is not silently promoted into AI long-term memory.
    assert "기억" in ko and "자동" in ko
    assert "memory" in en and "not" in en


def test_timezone_note_discloses_the_no_inference_rule() -> None:
    ko = _locale_value("calendar-appointment-timezone-note", "ko")
    en = _locale_value("calendar-appointment-timezone-note", "en")
    assert ko and en
    assert "IANA" in ko and "추측" in ko
    assert "IANA" in en and "never inferred" in en


def test_locale_defines_every_appointment_key_for_ko_and_en() -> None:
    source = _locale()
    for key in APPOINTMENT_LOCALE_KEYS:
        assert source.count(f'"{key}":') >= 2, key
    for key in APPOINTMENT_LOCALE_KEYS:
        assert _locale_value(key, "ko"), key
        assert _locale_value(key, "en"), key


def test_every_markup_locale_key_has_a_translation() -> None:
    form = _appointment_form_markup()
    keys = set(re.findall(r'data-locale-key="([^"]+)"', form))
    keys |= set(re.findall(r'data-locale-placeholder="([^"]+)"', form))
    assert keys, "appointment markup declares no locale keys"
    for key in sorted(keys):
        assert _locale_value(key, "ko"), key
        assert _locale_value(key, "en"), key


# ── authority reuse (no new endpoint, no new scope, no second authority) ──


def test_write_target_is_the_existing_registered_appointment_authority() -> None:
    source = _source()
    assert f'const APPOINTMENT_ROUTE = "{APPOINTMENT_ROUTE}";' in source
    assert "fetch(APPOINTMENT_ROUTE, {" in source
    # The route string is declared once and never duplicated as a literal.
    assert source.count(f'"{APPOINTMENT_ROUTE}"') == 1
    # It is the same path the product backend already registers for POST.
    factory = APP_FACTORY_PATH.read_text(encoding="utf-8")
    assert (
        f'Route("{APPOINTMENT_ROUTE}", calendar_appointments_create, methods=["POST"])'
        in factory
    )


def test_route_registers_workspace_and_owner_server_side_only() -> None:
    routes = ROUTES_PATH.read_text(encoding="utf-8")
    block = routes.split("async def calendar_appointments_create", 1)[1]
    block = block.split("async def calendar_appointments_list", 1)[0]
    # Scope is derived from the authenticated session, never from the body.
    assert "_resolve_memory_workspace(request, uid)" in block
    assert "owner_id=uid" in block
    assert 'body.get("workspace_id")' not in block
    assert 'body.get("owner_id")' not in block


def test_client_payload_keys_match_the_existing_route_contract() -> None:
    routes = ROUTES_PATH.read_text(encoding="utf-8")
    block = routes.split("async def calendar_appointments_create", 1)[1]
    block = block.split("async def calendar_appointments_list", 1)[0]
    accepted = set(re.findall(r'body\.get\("([a-z_]+)"', block))
    assert accepted == CLIENT_PAYLOAD_KEYS
    # Every key this client can build, as the builder itself constructs them: the
    # always-present literal plus the guarded conditional assignments.
    builder = _code_only().split("function buildAppointmentRequest(input) {", 1)[1]
    builder = builder.split("\n  }", 1)[0]
    literal = builder.split("const payload = {", 1)[1].split("};", 1)[0]
    literal_keys = set(re.findall(r"([a-z_]+):", literal))
    assert literal_keys == {"appointment_type", "title"}
    assigned = set(re.findall(r"payload\.([a-z_]+) =", builder))
    assert literal_keys | assigned == CLIENT_PAYLOAD_KEYS, sorted(CLIENT_PAYLOAD_KEYS ^ (literal_keys | assigned))
    assert literal_keys | assigned <= accepted


def test_only_the_two_native_write_methods_exist_in_the_module() -> None:
    source = _source()
    assert source.count('method: "POST"') == 2
    assert source.count(f'"{WORK_LOG_ROUTE}"') == 1
    assert source.count(f'"{APPOINTMENT_ROUTE}"') == 1
    assert not re.search(r"\b(PUT|PATCH|DELETE)\b", source)
    # The read path stays method-less (GET by default).
    read_block = source.split("async function load() {", 1)[1].split("function selectTab(", 1)[0]
    assert "method:" not in read_block


def test_appointment_write_request_shape_is_json_same_origin_and_uncached() -> None:
    source = _source()
    block = source.split("async function submitAppointment(event) {", 1)[1].split(
        "async function load() {", 1
    )[0]
    assert 'credentials: "same-origin"' in block
    assert 'cache: "no-store"' in block
    assert '"Content-Type": "application/json"' in block
    assert 'Accept: "application/json"' in block
    assert "body: JSON.stringify(built.payload)" in block


def _code_only() -> str:
    """static/calendar.js without its comments (scope claims live in prose too)."""
    source = re.sub(r"/\*.*?\*/", "", _source(), flags=re.DOTALL)
    return re.sub(r"^\s*//.*$", "", source, flags=re.MULTILINE)


def test_client_never_constructs_owner_workspace_or_tenant_scope() -> None:
    source = _code_only()
    for forbidden in (
        "user_id",
        "workspace_id",
        "owner_id",
        "tenant_id",
        "member_id",
        "workspace",
    ):
        assert forbidden not in source, forbidden


def test_no_second_appointment_authority_or_reminder_scheduler() -> None:
    source = _source()
    # One appointment route, one appointment builder, one interpreter.
    assert source.count("function buildAppointmentRequest") == 1
    assert source.count("function interpretAppointmentResponse") == 1
    assert source.count("APPOINTMENT_ROUTE") == 3  # declaration + api export + fetch
    # No client-side scheduling, queuing or polling of reminders.
    for forbidden in (
        "setInterval",
        "setTimeout",
        "Notification",
        "navigator",
        "serviceWorker",
        "cron",
    ):
        assert forbidden not in source, forbidden


def test_render_discipline_is_unchanged_for_the_appointment_path() -> None:
    source = _source()
    assert "innerHTML" not in source
    assert "insertAdjacentHTML" not in source
    assert "document.write" not in source
    assert "eval(" not in source
    assert "localStorage" not in source
    block = source.split("async function submitAppointment(event) {", 1)[1].split(
        "async function load() {", 1
    )[0]
    assert "showAppointmentStatus(" in block
    assert "appointmentStatus.textContent = text(key)" in source


def test_appointment_form_styles_use_shared_tokens_only() -> None:
    css = CALENDAR_CSS_PATH.read_text(encoding="utf-8")
    assert ".calendar-appointment-note" in css
    assert ".calendar-record-field[hidden]" in css
    assert "var(--accent-strong" in css
    assert "var(--line" in css


# ── behavioral harness: real calendar.js against a DOM stub ───────────────

_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
const CALENDAR_JS = fs.readFileSync(process.argv[2], "utf8");
const INDEX = fs.readFileSync(process.argv[3], "utf8");

const ids = [];
{
  const tagRe = /<([a-zA-Z0-9-]+)([^>]*)>/g;
  let m;
  while ((m = tagRe.exec(INDEX)) !== null) {
    const found = /\sid="([^"]+)"/.exec(m[2]);
    if (found && ids.indexOf(found[1]) < 0) ids.push(found[1]);
  }
}

function makeEl(tag) {
  const el = {
    tagName: tag, id: "", className: "", textContent: "", hidden: false,
    disabled: false, value: "", open: false, children: [], listeners: {},
    dataset: {}, style: {}, placeholder: "", maxLength: 0,
    classList: { add() {}, remove() {}, contains() { return false; }, toggle() {} },
  };
  el.setAttribute = (k, v) => { el[k] = String(v); };
  el.getAttribute = (k) => (k in el && k !== "listeners" ? el[k] : null);
  el.removeAttribute = (k) => { delete el[k]; };
  el.appendChild = (c) => { el.children.push(c); return c; };
  el.append = (...cs) => cs.forEach((c) => el.children.push(c));
  el.prepend = (...cs) => cs.forEach((c) => el.children.unshift(c));
  el.replaceChildren = (...cs) => { el.children = cs.slice(); };
  el.querySelector = () => null;
  el.querySelectorAll = () => [];
  el.closest = () => null;
  el.focus = () => {};
  el.blur = () => {};
  el.remove = () => {};
  el.addEventListener = (t, fn) => { (el.listeners[t] = el.listeners[t] || []).push(fn); };
  el.click = () => (el.listeners.click || []).forEach((fn) => fn({ preventDefault() {}, target: el }));
  el.dispatch = (t, event) => Promise.all((el.listeners[t] || []).map((fn) => fn(event || { preventDefault() {}, target: el })));
  return el;
}

const byId = {};
ids.forEach((id) => { const e = makeEl("div"); e.id = id; byId[id] = e; });

const shell = makeEl("div");
shell.dataset = { state: "home" };

const requests = [];
let mode = "created";
let lastBody = null;
function json(status, body) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}
async function fetchImpl(url, opts) {
  opts = opts || {};
  const method = String(opts.method || "GET").toUpperCase();
  const u = String(url);
  requests.push({
    url: u, method, headers: opts.headers || {},
    body: opts.body, credentials: opts.credentials, cache: opts.cache,
  });
  if (u.startsWith("/api/calendar/appointments") && method === "POST") {
    lastBody = opts.body ? JSON.parse(opts.body) : null;
    if (mode === "created") {
      // The REAL canonical projection shape (project_appointment().safe_dict()):
      // the four stable fields must be present or the client must not report a
      // saved appointment. The date is the one the server derives in the stated
      // zone, which for timed bodies is the local date of start_at.
      return json(201, {
        ok: true,
        appointment: {
          calendar_item_id: "item_apt_x",
          workspace_id: "ws_test",
          item_type: "appointment",
          title: lastBody.title,
          summary: lastBody.description || null,
          date: lastBody.date || String(lastBody.start_at).slice(0, 10),
          start_at: lastBody.start_at || null,
          end_at: lastBody.end_at || null,
          timezone: lastBody.timezone || null,
          all_day: lastBody.appointment_type === "all_day",
          source_type: "native_appointment",
          source_ref: "appointment:appointment_abc",
          created_at: "2026-09-23T00:00:00+00:00",
          updated_at: "2026-09-23T00:00:00+00:00",
          artifact: null,
        },
      });
    }
    if (mode === "unauthorized") return json(401, { ok: false, error: { code: "unauthorized" } });
    if (mode === "invalid") return json(400, { ok: false, error: { code: "invalid_timezone" } });
    if (mode === "malformed") return json(201, { ok: true });
    if (mode === "malformed_item") return json(201, { ok: true, appointment: "not-an-object" });
    if (mode === "empty_item") return json(201, { ok: true, appointment: {} });
    if (mode === "wrong_type_item") return json(201, { ok: true, appointment: { calendar_item_id: "item_log_a", item_type: "work_log", title: "x", date: "2026-09-23" } });
    if (mode === "not_ok") return json(201, { ok: false, appointment: { appointment_id: "x" } });
    if (mode === "network") throw new Error("boom");
    return json(500, { ok: false, error: { code: "appointment_creation_failed" } });
  }
  if (u.startsWith("/api/calendar/today") || u.startsWith("/api/calendar/upcoming")) {
    return json(200, { ok: true, projection: { items: [] } });
  }
  return json(404, {});
}

const doc = {
  readyState: "complete",
  documentElement: { lang: "ko", classList: { add() {}, remove() {}, contains() { return false; } } },
  body: makeEl("body"),
  activeElement: null,
  getElementById: (id) => byId[id] || null,
  querySelector: (sel) => (sel === ".app-shell" ? shell : null),
  querySelectorAll: () => [],
  createElement: (tag) => makeEl(tag),
  addEventListener() {},
};

const sandbox = {
  document: doc, fetch: fetchImpl, console, Intl, Date, JSON, Number, Object,
  String, Array, RegExp, Promise, setTimeout, clearTimeout, Error,
  __padiemLocale: { text: (key) => "T:" + key },
};
sandbox.window = sandbox;
sandbox.window.addEventListener = () => {};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

const checks = {};
function fail(message) {
  console.log(JSON.stringify({ ok: false, error: message, checks, requests }));
  process.exit(0);
}

vm.runInContext(CALENDAR_JS, sandbox, { filename: "calendar.js" });

(async () => {
  const tick = () => new Promise((r) => setTimeout(r, 5));
  const type = byId.calendarAppointmentType;
  const title = byId.calendarAppointmentTitle;
  const dateField = byId.calendarAppointmentDate;
  const zoneField = byId.calendarAppointmentTimeZone;
  const startField = byId.calendarAppointmentStart;
  const endField = byId.calendarAppointmentEnd;
  const reminder = byId.calendarAppointmentReminder;
  const description = byId.calendarAppointmentDescription;
  const button = byId.calendarAppointmentSubmit;
  const status = byId.calendarAppointmentStatus;
  const form = byId.calendarAppointmentForm;
  const zoneWrapper = byId.calendarAppointmentTimeZoneField;
  const startWrapper = byId.calendarAppointmentStartField;
  const endWrapper = byId.calendarAppointmentEndField;

  const submit = () => form.dispatch("submit");
  const changeType = (value) => { type.value = value; return type.dispatch("change"); };
  function postOf(from) {
    return requests.slice(from).find((r) => r.method === "POST" && r.url.indexOf("/api/calendar/appointments") === 0);
  }

  // 1) Opening the calendar performs the existing read-only load only.
  byId.calendarNavButton.click();
  await tick();
  await tick();
  checks.OPEN_LOADS_TODAY_ONLY =
    requests.length === 1 &&
    requests[0].method === "GET" &&
    requests[0].url.indexOf("/api/calendar/today?timezone=") === 0;
  if (!checks.OPEN_LOADS_TODAY_ONLY) fail("OPEN " + JSON.stringify(requests));
  checks.DATE_DEFAULT_IS_EXPLICIT_ZONE_TODAY =
    /^\d{4}-\d{2}-\d{2}$/.test(dateField.value) &&
    dateField.value === sandbox.window.PadiemCalendarUI.localDateInZone(
      sandbox.window.PadiemCalendarUI.browserTimezone()
    );
  if (!checks.DATE_DEFAULT_IS_EXPLICIT_ZONE_TODAY) fail("DATE_DEFAULT " + dateField.value);
  // The zone input is pre-filled with the browser's own zone as an explicit,
  // editable default. Checked here, before any case below writes to the field,
  // so the assertion never depends on which zone the host machine is in.
  checks.TIME_ZONE_FIELD_IS_PRE_FILLED_WITH_THE_BROWSER_ZONE =
    typeof zoneField.value === "string" && zoneField.value.length > 0 &&
    zoneField.value === sandbox.window.PadiemCalendarUI.browserTimezone();
  if (!checks.TIME_ZONE_FIELD_IS_PRE_FILLED_WITH_THE_BROWSER_ZONE) {
    fail("ZONE_PREFILL " + JSON.stringify({ value: zoneField.value, browser: sandbox.window.PadiemCalendarUI.browserTimezone() }));
  }

  // 2) date_only: the date alone is sent, and no time field is visible.
  await changeType("date_only");
  checks.DATE_ONLY_HIDES_TIME_FIELDS =
    zoneWrapper.hidden === true && startWrapper.hidden === true && endWrapper.hidden === true;
  if (!checks.DATE_ONLY_HIDES_TIME_FIELDS) fail("DATE_ONLY_HIDDEN " + JSON.stringify({ z: zoneWrapper.hidden, s: startWrapper.hidden, e: endWrapper.hidden }));

  let before = requests.length;
  dateField.value = "2026-09-23";
  title.value = "   A사 계약 미팅   ";
  // Even if stale time values linger in the DOM they must never be sent.
  startField.value = "10:00";
  endField.value = "11:00";
  zoneField.value = "Asia/Seoul";
  description.value = "";
  reminder.value = "";
  await submit();
  await tick();
  let post = postOf(before);
  checks.DATE_ONLY_CREATE_IS_BOUNDED =
    !!post &&
    post.url === "/api/calendar/appointments" &&
    post.credentials === "same-origin" &&
    post.cache === "no-store" &&
    post.headers["Content-Type"] === "application/json" &&
    post.headers["Accept"] === "application/json";
  if (!checks.DATE_ONLY_CREATE_IS_BOUNDED) fail("DATE_ONLY_SHAPE " + JSON.stringify(requests.slice(before)));
  let body = JSON.parse(post.body);
  checks.DATE_ONLY_BODY_IS_DATE_ONLY =
    JSON.stringify(Object.keys(body).sort()) === JSON.stringify(["appointment_type", "date", "title"]) &&
    body.appointment_type === "date_only" &&
    body.date === "2026-09-23" &&
    body.title === "A사 계약 미팅";
  if (!checks.DATE_ONLY_BODY_IS_DATE_ONLY) fail("DATE_ONLY_BODY " + JSON.stringify(body));
  checks.DATE_ONLY_CREATE_REFRESHES_THE_CURRENT_PROJECTION =
    requests.slice(before).some((r) => r.method === "GET" && r.url.indexOf("/api/calendar/today") === 0);
  if (!checks.DATE_ONLY_CREATE_REFRESHES_THE_CURRENT_PROJECTION) fail("DATE_ONLY_REFRESH " + JSON.stringify(requests.slice(before)));

  // 3) all_day: still date-only, and never a fabricated start/end.
  await changeType("all_day");
  checks.ALL_DAY_HIDES_TIME_FIELDS =
    zoneWrapper.hidden === true && startWrapper.hidden === true && endWrapper.hidden === true;
  if (!checks.ALL_DAY_HIDES_TIME_FIELDS) fail("ALL_DAY_HIDDEN");
  before = requests.length;
  title.value = "전사 워크숍";
  dateField.value = "2026-10-01";
  await submit();
  await tick();
  post = postOf(before);
  body = JSON.parse(post.body);
  checks.ALL_DAY_BODY_HAS_NO_FAKE_TIME =
    JSON.stringify(Object.keys(body).sort()) === JSON.stringify(["appointment_type", "date", "title"]) &&
    body.appointment_type === "all_day" &&
    body.date === "2026-10-01" &&
    body.start_at === undefined &&
    body.end_at === undefined &&
    body.timezone === undefined;
  if (!checks.ALL_DAY_BODY_HAS_NO_FAKE_TIME) fail("ALL_DAY_BODY " + JSON.stringify(body));

  // 4) timed: an explicit IANA zone produces an offset-bearing start.
  await changeType("timed");
  checks.TIMED_REVEALS_TIME_FIELDS =
    zoneWrapper.hidden === false && startWrapper.hidden === false && endWrapper.hidden === false;
  if (!checks.TIMED_REVEALS_TIME_FIELDS) fail("TIMED_HIDDEN");

  before = requests.length;
  title.value = "A사 계약 미팅";
  dateField.value = "2026-09-23";
  zoneField.value = "Asia/Seoul";
  startField.value = "10:00";
  endField.value = "11:30";
  reminder.value = "30";
  description.value = "  계약 조건 확인  ";
  await submit();
  await tick();
  post = postOf(before);
  body = JSON.parse(post.body);
  checks.TIMED_BODY_IS_EXPLICIT_AND_OFFSET_BEARING =
    body.appointment_type === "timed" &&
    body.timezone === "Asia/Seoul" &&
    body.start_at === "2026-09-23T10:00:00+09:00" &&
    body.end_at === "2026-09-23T11:30:00+09:00" &&
    body.reminder_minutes === 30 &&
    body.description === "계약 조건 확인" &&
    body.date === undefined;
  if (!checks.TIMED_BODY_IS_EXPLICIT_AND_OFFSET_BEARING) fail("TIMED_BODY " + JSON.stringify(body));
  checks.TIMED_START_AND_END_ALWAYS_CARRY_AN_OFFSET =
    /(?:Z|[+-]\d{2}:\d{2})$/.test(body.start_at) &&
    /(?:Z|[+-]\d{2}:\d{2})$/.test(body.end_at) &&
    !/[+-]\d{2}:\d{2}\.\d+$/.test(body.start_at);
  if (!checks.TIMED_START_AND_END_ALWAYS_CARRY_AN_OFFSET) fail("OFFSET " + JSON.stringify(body));
  checks.SUCCESS_CONFIRMATION_IS_TEXT_AND_TITLE_CLEARS =
    status.textContent === "T:calendar-appointment-created" &&
    status.hidden === false &&
    title.value === "" &&
    dateField.value === sandbox.window.PadiemCalendarUI.localDateInZone(
      sandbox.window.PadiemCalendarUI.browserTimezone()
    );
  if (!checks.SUCCESS_CONFIRMATION_IS_TEXT_AND_TITLE_CLEARS) {
    fail("SUCCESS_STATE " + JSON.stringify({ text: status.textContent, hidden: status.hidden, title: title.value }));
  }

  // 5) timed with end omitted: only start_at is sent (end is optional).
  before = requests.length;
  title.value = "짧은 통화";
  dateField.value = "2026-09-24";
  zoneField.value = "Asia/Seoul";
  startField.value = "14:00";
  endField.value = "";
  reminder.value = "";
  description.value = "";
  await submit();
  await tick();
  body = JSON.parse(postOf(before).body);
  checks.TIMED_WITHOUT_END_IS_ACCEPTED =
    body.start_at === "2026-09-24T14:00:00+09:00" && body.end_at === undefined;
  if (!checks.TIMED_WITHOUT_END_IS_ACCEPTED) fail("TIMED_NO_END " + JSON.stringify(body));

  // 6) A different zone produces that zone's own offset, not the browser's.
  before = requests.length;
  title.value = "베를린 콜";
  dateField.value = "2026-07-01";
  zoneField.value = "Europe/Berlin";
  startField.value = "12:00";
  await submit();
  await tick();
  body = JSON.parse(postOf(before).body);
  checks.ZONE_COMES_FROM_THE_FIELD_NOT_THE_BROWSER =
    body.timezone === "Europe/Berlin" && body.start_at === "2026-07-01T12:00:00+02:00";
  if (!checks.ZONE_COMES_FROM_THE_FIELD_NOT_THE_BROWSER) fail("BERLIN " + JSON.stringify(body));

  // 6b) The explicitly typed zone wins even when it is NOT the browser's zone.
  // The comparison zone is picked from the host's own zone, so this holds on any
  // CI runner (whose zone is UTC) and on any developer machine alike.
  const browserZone = sandbox.window.PadiemCalendarUI.browserTimezone();
  const otherZone = browserZone === "Asia/Seoul" ? "America/New_York" : "Asia/Seoul";
  const otherOffset = otherZone === "Asia/Seoul" ? "+09:00" : "-05:00";
  before = requests.length;
  title.value = "다른 시간대 확인";
  dateField.value = "2026-01-15";
  zoneField.value = otherZone;
  startField.value = "09:00";
  endField.value = "";
  await submit();
  await tick();
  body = JSON.parse(postOf(before).body);
  checks.EXPLICIT_ZONE_WINS_OVER_THE_BROWSER_DEFAULT =
    otherZone !== browserZone &&
    body.timezone === otherZone &&
    body.start_at === "2026-01-15T09:00:00" + otherOffset;
  if (!checks.EXPLICIT_ZONE_WINS_OVER_THE_BROWSER_DEFAULT) {
    fail("ZONE_WINS " + JSON.stringify({ body: body, browser: browserZone, other: otherZone }));
  }

  // 7) Pre-request rejections: nothing is sent and nothing claims success.
  async function rejectedWithoutRequest(name, setup, expectedText) {
    const count = requests.length;
    mode = "created";
    await setup();
    await submit();
    await tick();
    checks[name] = status.textContent === "T:" + expectedText && requests.length === count;
    if (!checks[name]) fail(name + " " + JSON.stringify({ text: status.textContent, added: requests.slice(count) }));
  }
  await rejectedWithoutRequest(
    "TIMED_MISSING_TIMEZONE_IS_REJECTED_WITHOUT_A_REQUEST",
    async () => { await changeType("timed"); title.value = "시간대 없음"; dateField.value = "2026-09-23"; zoneField.value = "  "; startField.value = "10:00"; },
    "calendar-appointment-invalid"
  );
  await rejectedWithoutRequest(
    "TIMED_INVALID_TIMEZONE_IS_REJECTED_WITHOUT_A_REQUEST",
    async () => { zoneField.value = "Not/AZone"; startField.value = "10:00"; },
    "calendar-appointment-invalid"
  );
  await rejectedWithoutRequest(
    "TIMED_MISSING_START_IS_REJECTED_WITHOUT_A_REQUEST",
    async () => { zoneField.value = "Asia/Seoul"; startField.value = ""; },
    "calendar-appointment-invalid"
  );
  await rejectedWithoutRequest(
    "TIMED_MALFORMED_START_IS_REJECTED_WITHOUT_A_REQUEST",
    async () => { zoneField.value = "Asia/Seoul"; startField.value = "25:99"; },
    "calendar-appointment-invalid"
  );
  await rejectedWithoutRequest(
    "BLANK_TITLE_IS_REJECTED_WITHOUT_A_REQUEST",
    async () => { await changeType("date_only"); title.value = "   "; dateField.value = "2026-09-23"; },
    "calendar-appointment-invalid"
  );
  await rejectedWithoutRequest(
    "MALFORMED_DATE_IS_REJECTED_WITHOUT_A_REQUEST",
    async () => { title.value = "날짜 확인"; dateField.value = "2026/09/23"; },
    "calendar-appointment-invalid"
  );
  await rejectedWithoutRequest(
    "MISSING_DATE_IS_REJECTED_WITHOUT_A_REQUEST",
    async () => { dateField.value = ""; },
    "calendar-appointment-invalid"
  );
  // The DST spring-forward gap: New York jumps 02:00 -> 03:00 on 2026-03-08, so
  // 02:30 does not exist there. It must be refused BEFORE any request, never
  // converted into some other real instant.
  await rejectedWithoutRequest(
    "NONEXISTENT_DST_WALL_CLOCK_IS_REJECTED_WITHOUT_A_REQUEST",
    async () => {
      await changeType("timed");
      title.value = "DST 갭";
      dateField.value = "2026-03-08";
      zoneField.value = "America/New_York";
      startField.value = "02:30";
      endField.value = "";
    },
    "calendar-appointment-invalid"
  );
  // ...while the very next minute that DOES exist still submits normally.
  before = requests.length;
  mode = "created";
  startField.value = "03:00";
  await submit();
  await tick();
  body = JSON.parse(postOf(before).body);
  checks.DST_TIME_AFTER_THE_JUMP_STILL_SUBMITS =
    body.timezone === "America/New_York" && body.start_at === "2026-03-08T03:00:00-04:00";
  if (!checks.DST_TIME_AFTER_THE_JUMP_STILL_SUBMITS) fail("DST_AFTER_JUMP " + JSON.stringify(body));

  // 8) Every failure branch maps to a bounded message, never a saved state.
  async function failureCase(nextMode, expectedText) {
    mode = nextMode;
    const count = requests.length;
    await changeType("date_only");
    title.value = "상태 확인";
    dateField.value = "2026-09-25";
    await submit();
    await tick();
    const key = "FAILURE_" + nextMode.toUpperCase();
    checks[key] = status.textContent === "T:" + expectedText && requests.length > count;
    if (!checks[key]) fail(key + " " + JSON.stringify({ text: status.textContent, added: requests.slice(count) }));
  }
  await failureCase("unauthorized", "calendar-appointment-unauthorized");
  await failureCase("invalid", "calendar-appointment-invalid");
  await failureCase("server_error", "calendar-appointment-unavailable");
  await failureCase("malformed", "calendar-appointment-unavailable");
  await failureCase("malformed_item", "calendar-appointment-unavailable");
  await failureCase("empty_item", "calendar-appointment-unavailable");
  await failureCase("wrong_type_item", "calendar-appointment-unavailable");
  await failureCase("not_ok", "calendar-appointment-unavailable");
  await failureCase("network", "calendar-appointment-unavailable");

  // 9) The whole journey stayed inside the three existing calendar routes.
  mode = "created";
  const allowed = ["/api/calendar/today", "/api/calendar/upcoming", "/api/calendar/appointments", "/api/calendar/work-logs"];
  const methods = Array.from(new Set(requests.map((r) => r.method))).sort();
  checks.NO_UNKNOWN_ROUTE_AND_NO_OTHER_METHOD =
    requests.every((r) => allowed.some((prefix) => r.url.indexOf(prefix) === 0)) &&
    JSON.stringify(methods) === JSON.stringify(["GET", "POST"]);
  if (!checks.NO_UNKNOWN_ROUTE_AND_NO_OTHER_METHOD) fail("ROUTES " + JSON.stringify({ methods, urls: requests.map((r) => r.url) }));
  checks.EVERY_WRITE_BODY_AVOIDS_SCOPE_FIELDS = requests
    .filter((r) => r.method === "POST")
    .every((r) => Object.keys(JSON.parse(r.body)).every((k) =>
      ["appointment_type", "title", "description", "date", "start_at", "end_at", "timezone", "reminder_minutes"].indexOf(k) >= 0
    ));
  if (!checks.EVERY_WRITE_BODY_AVOIDS_SCOPE_FIELDS) fail("SCOPE_LEAK " + JSON.stringify(requests.filter((r) => r.method === "POST")));
  checks.EVERY_TIMED_BODY_IS_OFFSET_BEARING = requests
    .filter((r) => r.method === "POST" && JSON.parse(r.body).appointment_type === "timed")
    .every((r) => {
      const b = JSON.parse(r.body);
      return typeof b.timezone === "string" && b.timezone.length > 0 &&
        /(?:Z|[+-]\d{2}:\d{2})$/.test(b.start_at) &&
        (b.end_at === undefined || /(?:Z|[+-]\d{2}:\d{2})$/.test(b.end_at));
    });
  if (!checks.EVERY_TIMED_BODY_IS_OFFSET_BEARING) fail("NAIVE_RISK " + JSON.stringify(requests.filter((r) => r.method === "POST" && JSON.parse(r.body).appointment_type === "timed")));
  checks.EVERY_DATE_ONLY_BODY_HAS_NO_TIME_FIELDS = requests
    .filter((r) => r.method === "POST" && ["date_only", "all_day"].indexOf(JSON.parse(r.body).appointment_type) >= 0)
    .every((r) => {
      const b = JSON.parse(r.body);
      return typeof b.date === "string" && b.start_at === undefined && b.end_at === undefined && b.timezone === undefined;
    });
  if (!checks.EVERY_DATE_ONLY_BODY_HAS_NO_TIME_FIELDS) fail("DATE_ONLY_LEAK");

  console.log(JSON.stringify({ ok: true, checks, requests: requests.length }));
  process.exit(0);
})().catch((e) => {
  console.log(JSON.stringify({ ok: false, error: String((e && e.stack) || e) }));
  process.exit(0);
});
"""


def _run_harness() -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required for the behavioral harness"
    harness_path = ROOT / "tests" / "_calendar_ui_appointment_create_harness.js"
    harness_path.write_text(_HARNESS, encoding="utf-8")
    try:
        completed = subprocess.run(
            [node, str(harness_path), str(CALENDAR_JS_PATH), str(INDEX_PATH)],
            capture_output=True,
            text=True,
            timeout=180,
        )
    finally:
        harness_path.unlink(missing_ok=True)
    assert completed.returncode == 0, f"harness exited {completed.returncode}: {completed.stderr}"
    line = completed.stdout.strip().splitlines()[-1] if completed.stdout.strip() else "{}"
    return json.loads(line)


_HARNESS_CHECKS = (
    "OPEN_LOADS_TODAY_ONLY",
    "DATE_DEFAULT_IS_EXPLICIT_ZONE_TODAY",
    "DATE_ONLY_HIDES_TIME_FIELDS",
    "DATE_ONLY_CREATE_IS_BOUNDED",
    "DATE_ONLY_BODY_IS_DATE_ONLY",
    "DATE_ONLY_CREATE_REFRESHES_THE_CURRENT_PROJECTION",
    "ALL_DAY_HIDES_TIME_FIELDS",
    "ALL_DAY_BODY_HAS_NO_FAKE_TIME",
    "TIMED_REVEALS_TIME_FIELDS",
    "TIME_ZONE_FIELD_IS_PRE_FILLED_WITH_THE_BROWSER_ZONE",
    "TIMED_BODY_IS_EXPLICIT_AND_OFFSET_BEARING",
    "TIMED_START_AND_END_ALWAYS_CARRY_AN_OFFSET",
    "SUCCESS_CONFIRMATION_IS_TEXT_AND_TITLE_CLEARS",
    "TIMED_WITHOUT_END_IS_ACCEPTED",
    "ZONE_COMES_FROM_THE_FIELD_NOT_THE_BROWSER",
    "EXPLICIT_ZONE_WINS_OVER_THE_BROWSER_DEFAULT",
    "TIMED_MISSING_TIMEZONE_IS_REJECTED_WITHOUT_A_REQUEST",
    "TIMED_INVALID_TIMEZONE_IS_REJECTED_WITHOUT_A_REQUEST",
    "TIMED_MISSING_START_IS_REJECTED_WITHOUT_A_REQUEST",
    "TIMED_MALFORMED_START_IS_REJECTED_WITHOUT_A_REQUEST",
    "BLANK_TITLE_IS_REJECTED_WITHOUT_A_REQUEST",
    "MALFORMED_DATE_IS_REJECTED_WITHOUT_A_REQUEST",
    "MISSING_DATE_IS_REJECTED_WITHOUT_A_REQUEST",
    "NONEXISTENT_DST_WALL_CLOCK_IS_REJECTED_WITHOUT_A_REQUEST",
    "DST_TIME_AFTER_THE_JUMP_STILL_SUBMITS",
    "FAILURE_UNAUTHORIZED",
    "FAILURE_INVALID",
    "FAILURE_SERVER_ERROR",
    "FAILURE_MALFORMED",
    "FAILURE_MALFORMED_ITEM",
    "FAILURE_EMPTY_ITEM",
    "FAILURE_WRONG_TYPE_ITEM",
    "FAILURE_NOT_OK",
    "FAILURE_NETWORK",
    "NO_UNKNOWN_ROUTE_AND_NO_OTHER_METHOD",
    "EVERY_WRITE_BODY_AVOIDS_SCOPE_FIELDS",
    "EVERY_TIMED_BODY_IS_OFFSET_BEARING",
    "EVERY_DATE_ONLY_BODY_HAS_NO_TIME_FIELDS",
)


def test_behavioral_harness_passes() -> None:
    payload = _run_harness()
    assert payload.get("ok") is True, payload
    for name in _HARNESS_CHECKS:
        assert payload["checks"].get(name) is True, name


# ── pure helper contracts (Node) ─────────────────────────────────────────


def test_appointment_helpers_build_the_contract_payload_or_fail_closed() -> None:
    script = f"""
    global.window = {{}};
    require({json.dumps(str(CALENDAR_JS_PATH))});
    const ui = window.PadiemCalendarUI;
    const keys = (r) => (r.ok ? Object.keys(r.payload).sort() : null);
    process.stdout.write(JSON.stringify({{
      route: ui.APPOINTMENT_ROUTE,
      types: ui.APPOINTMENT_TYPES,
      dateOnly: ui.buildAppointmentRequest({{ appointment_type: "date_only", title: "  x  ", date: "2026-09-23", start_time: "10:00", timezone: "Asia/Seoul" }}),
      dateOnlyKeys: keys(ui.buildAppointmentRequest({{ appointment_type: "date_only", title: "x", date: "2026-09-23" }})),
      allDay: ui.buildAppointmentRequest({{ appointment_type: "all_day", title: "x", date: "2026-10-01" }}),
      timed: ui.buildAppointmentRequest({{ appointment_type: "timed", title: "x", date: "2026-09-23", timezone: "Asia/Seoul", start_time: "10:00", end_time: "11:30", reminder_minutes: "30", description: " d " }}),
      timedNoEnd: ui.buildAppointmentRequest({{ appointment_type: "timed", title: "x", date: "2026-09-23", timezone: "Asia/Seoul", start_time: "10:00" }}),
      timedNoZone: ui.buildAppointmentRequest({{ appointment_type: "timed", title: "x", date: "2026-09-23", start_time: "10:00" }}),
      timedBlankZone: ui.buildAppointmentRequest({{ appointment_type: "timed", title: "x", date: "2026-09-23", timezone: "   ", start_time: "10:00" }}),
      timedBadZone: ui.buildAppointmentRequest({{ appointment_type: "timed", title: "x", date: "2026-09-23", timezone: "Not/AZone", start_time: "10:00" }}),
      timedNoStart: ui.buildAppointmentRequest({{ appointment_type: "timed", title: "x", date: "2026-09-23", timezone: "Asia/Seoul" }}),
      timedBadEnd: ui.buildAppointmentRequest({{ appointment_type: "timed", title: "x", date: "2026-09-23", timezone: "Asia/Seoul", start_time: "10:00", end_time: "25:00" }}),
      badType: ui.buildAppointmentRequest({{ appointment_type: "weekly", title: "x", date: "2026-09-23" }}),
      emptyType: ui.buildAppointmentRequest({{ appointment_type: "   ", title: "x", date: "2026-09-23" }}),
      blankTitle: ui.buildAppointmentRequest({{ appointment_type: "date_only", title: "   ", date: "2026-09-23" }}),
      missingDate: ui.buildAppointmentRequest({{ appointment_type: "date_only", title: "x" }}),
      badDate: ui.buildAppointmentRequest({{ appointment_type: "all_day", title: "x", date: "2026/10/01" }}),
      nullInput: ui.buildAppointmentRequest(null),
      reminderZero: ui.buildAppointmentRequest({{ appointment_type: "date_only", title: "x", date: "2026-09-23", reminder_minutes: 0 }}),
      reminderMax: ui.buildAppointmentRequest({{ appointment_type: "date_only", title: "x", date: "2026-09-23", reminder_minutes: 40320 }}),
      reminderTooBig: ui.buildAppointmentRequest({{ appointment_type: "date_only", title: "x", date: "2026-09-23", reminder_minutes: 40321 }}),
      reminderNegative: ui.buildAppointmentRequest({{ appointment_type: "date_only", title: "x", date: "2026-09-23", reminder_minutes: -1 }}),
      reminderText: ui.buildAppointmentRequest({{ appointment_type: "date_only", title: "x", date: "2026-09-23", reminder_minutes: "abc" }}),
      seoul: ui.zonedLocalToIso("2026-09-23", "10:00", "Asia/Seoul"),
      berlinSummer: ui.zonedLocalToIso("2026-07-01", "12:00", "Europe/Berlin"),
      berlinWinter: ui.zonedLocalToIso("2026-12-01", "12:00", "Europe/Berlin"),
      kolkata: ui.zonedLocalToIso("2026-09-23", "10:00", "Asia/Kolkata"),
      utc: ui.zonedLocalToIso("2026-09-23", "10:00", "UTC"),
      newYork: ui.zonedLocalToIso("2026-01-15", "09:00", "America/New_York"),
      badZoneIso: ui.zonedLocalToIso("2026-09-23", "10:00", "Not/AZone"),
      emptyZoneIso: ui.zonedLocalToIso("2026-09-23", "10:00", ""),
      badDateIso: ui.zonedLocalToIso("2026/09/23", "10:00", "Asia/Seoul"),
      badTimeIso: ui.zonedLocalToIso("2026-09-23", "25:99", "Asia/Seoul"),
      emptyTimeIso: ui.zonedLocalToIso("2026-09-23", "", "Asia/Seoul"),
      dstAfterJump: ui.zonedLocalToIso("2026-03-08", "03:00", "America/New_York"),
      dstAfterJumpLate: ui.zonedLocalToIso("2026-03-08", "03:30", "America/New_York"),
      dstAfterJumpBerlin: ui.zonedLocalToIso("2026-03-29", "03:30", "Europe/Berlin"),
      dstGapNy: ui.zonedLocalToIso("2026-03-08", "02:30", "America/New_York"),
      dstGapNyEdge: ui.zonedLocalToIso("2026-03-08", "02:00", "America/New_York"),
      dstGapNyLast: ui.zonedLocalToIso("2026-03-08", "02:59", "America/New_York"),
      dstGapBerlin: ui.zonedLocalToIso("2026-03-29", "02:30", "Europe/Berlin"),
      dstGapBuilder: ui.buildAppointmentRequest({{ appointment_type: "timed", title: "x", date: "2026-03-08", timezone: "America/New_York", start_time: "02:30" }}),
      dstFoldNy: ui.zonedLocalToIso("2026-11-01", "01:30", "America/New_York"),
      dstFoldBerlin: ui.zonedLocalToIso("2026-10-25", "02:30", "Europe/Berlin"),
      rtSeoul: ui.zoneWallClock("Asia/Seoul", Date.parse("2026-09-23T10:00:00+09:00")),
      rtAfterJump: ui.zoneWallClock("America/New_York", Date.parse("2026-03-08T03:00:00-04:00")),
      rtFoldNy: ui.zoneWallClock("America/New_York", Date.parse("2026-11-01T01:30:00-04:00")),
      rtGapWouldBe: ui.zoneWallClock("America/New_York", Date.parse("2026-03-08T02:30:00-04:00")),
      rtBadZone: ui.zoneWallClock("Not/AZone", Date.parse("2026-09-23T10:00:00Z")),
      rtEmptyZone: ui.zoneWallClock("", Date.parse("2026-09-23T10:00:00Z")),
      offsetSeoul: ui.formatUtcOffset(540),
      offsetNegative: ui.formatUtcOffset(-300),
      offsetHalf: ui.formatUtcOffset(330),
      created: ui.interpretAppointmentResponse(201, {{ ok: true, appointment: {{ calendar_item_id: "item_apt_a", item_type: "appointment", title: "x", date: "2026-09-23" }} }}),
      createdEmptyItem: ui.interpretAppointmentResponse(201, {{ ok: true, appointment: {{}} }}),
      createdNullItem: ui.interpretAppointmentResponse(201, {{ ok: true, appointment: null }}),
      createdArrayItem: ui.interpretAppointmentResponse(201, {{ ok: true, appointment: [] }}),
      createdNoDate: ui.interpretAppointmentResponse(201, {{ ok: true, appointment: {{ calendar_item_id: "item_apt_a", item_type: "appointment", title: "x" }} }}),
      createdWrongType: ui.interpretAppointmentResponse(201, {{ ok: true, appointment: {{ calendar_item_id: "item_log_a", item_type: "work_log", title: "x", date: "2026-09-23" }} }}),
      createdEmptyTitle: ui.interpretAppointmentResponse(201, {{ ok: true, appointment: {{ calendar_item_id: "item_apt_a", item_type: "appointment", title: "   ", date: "2026-09-23" }} }}),
      createdEmptyId: ui.interpretAppointmentResponse(201, {{ ok: true, appointment: {{ calendar_item_id: "  ", item_type: "appointment", title: "x", date: "2026-09-23" }} }}),
      createdBadDate: ui.interpretAppointmentResponse(201, {{ ok: true, appointment: {{ calendar_item_id: "item_apt_a", item_type: "appointment", title: "x", date: "2026/09/23" }} }}),
      createdNoItem: ui.interpretAppointmentResponse(201, {{ ok: true }}),
      createdNotOk: ui.interpretAppointmentResponse(201, {{ ok: false, appointment: {{ appointment_id: "a" }} }}),
      createdStringItem: ui.interpretAppointmentResponse(201, {{ ok: true, appointment: "x" }}),
      nullBody: ui.interpretAppointmentResponse(201, null),
      unauthorized: ui.interpretAppointmentResponse(401, {{}}),
      invalid: ui.interpretAppointmentResponse(400, {{}}),
      forbidden: ui.interpretAppointmentResponse(403, {{}}),
      noStore: ui.interpretAppointmentResponse(503, {{}}),
      server: ui.interpretAppointmentResponse(500, {{}}),
      statusKeys: ui.APPOINTMENT_STATUS_KEYS,
    }}));
    """
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    data = json.loads(completed.stdout)

    assert data["route"] == APPOINTMENT_ROUTE
    assert data["types"] == ["date_only", "all_day", "timed"]

    # date_only / all_day: the date alone, and stale time values are ignored.
    assert data["dateOnlyKeys"] == ["appointment_type", "date", "title"]
    assert data["dateOnly"]["payload"]["title"] == "x"
    assert data["allDay"]["payload"]["date"] == "2026-10-01"
    assert data["allDay"]["payload"]["appointment_type"] == "all_day"

    # timed: explicit zone + offset-bearing start, optional end, no date key.
    timed = data["timed"]["payload"]
    assert timed["timezone"] == "Asia/Seoul"
    assert timed["start_at"] == "2026-09-23T10:00:00+09:00"
    assert timed["end_at"] == "2026-09-23T11:30:00+09:00"
    assert timed["reminder_minutes"] == 30
    assert timed["description"] == "d"
    assert "date" not in timed
    assert "end_at" not in data["timedNoEnd"]["payload"]
    assert OFFSET_SUFFIX.search(timed["start_at"])
    assert OFFSET_SUFFIX.search(timed["end_at"])

    # timed fail-closed branches.
    assert data["timedNoZone"] == {"ok": False, "reason": "timezone_required"}
    assert data["timedBlankZone"] == {"ok": False, "reason": "timezone_required"}
    assert data["timedBadZone"] == {"ok": False, "reason": "invalid_start"}
    assert data["timedNoStart"] == {"ok": False, "reason": "invalid_start"}
    assert data["timedBadEnd"] == {"ok": False, "reason": "invalid_end"}

    # type / title / date / reminder fail-closed branches.
    assert data["badType"] == {"ok": False, "reason": "invalid_type"}
    assert data["emptyType"] == {"ok": False, "reason": "invalid_type"}
    assert data["blankTitle"] == {"ok": False, "reason": "title_required"}
    assert data["missingDate"] == {"ok": False, "reason": "invalid_date"}
    assert data["badDate"] == {"ok": False, "reason": "invalid_date"}
    assert data["nullInput"] == {"ok": False, "reason": "invalid_type"}
    assert data["reminderZero"]["payload"]["reminder_minutes"] == 0
    assert data["reminderMax"]["payload"]["reminder_minutes"] == MAX_REMINDER_MINUTES
    assert data["reminderTooBig"] == {"ok": False, "reason": "invalid_reminder"}
    assert data["reminderNegative"] == {"ok": False, "reason": "invalid_reminder"}
    assert data["reminderText"] == {"ok": False, "reason": "invalid_reminder"}

    # zone arithmetic is explicit and always offset-bearing.
    assert data["seoul"] == "2026-09-23T10:00:00+09:00"
    assert data["berlinSummer"] == "2026-07-01T12:00:00+02:00"
    assert data["berlinWinter"] == "2026-12-01T12:00:00+01:00"
    assert data["kolkata"] == "2026-09-23T10:00:00+05:30"
    assert data["utc"] == "2026-09-23T10:00:00+00:00"
    assert data["newYork"] == "2026-01-15T09:00:00-05:00"

    # Spring-forward DST GAP: New York jumps 02:00 -> 03:00 on 2026-03-08, so the
    # whole 02:00-02:59 wall clock does not exist and must fail closed. (03:00 and
    # later DO exist, after the jump.)
    assert data["dstGapNy"] == ""
    assert data["dstGapNyEdge"] == ""
    assert data["dstGapNyLast"] == ""
    assert data["dstGapBerlin"] == ""   # Berlin jumps 02:00 -> 03:00 on 2026-03-29
    assert data["dstGapBuilder"] == {"ok": False, "reason": "invalid_start"}
    # Times that exist immediately after the jump still convert, in the new offset.
    assert data["dstAfterJump"] == "2026-03-08T03:00:00-04:00"
    assert data["dstAfterJumpLate"] == "2026-03-08T03:30:00-04:00"
    assert data["dstAfterJumpBerlin"] == "2026-03-29T03:30:00+02:00"

    # Fall-back AMBIGUOUS times exist twice; the policy is deterministic and never
    # drifts the entered wall clock:
    #   - New York 2026-11-01 01:30 is both 05:30Z (EDT, earlier) and 06:30Z (EST);
    #     the earlier instant wins -> -04:00.
    #   - Berlin 2026-10-25 02:30 is both 00:30Z (CEST, earlier) and 01:30Z (CET);
    #     the earlier instant wins -> +02:00.
    assert data["dstFoldNy"] == "2026-11-01T01:30:00-04:00"
    assert data["dstFoldBerlin"] == "2026-10-25T02:30:00+02:00"

    # Round-trip law: every value this client emits reads back in its own stated
    # zone as exactly the wall clock the user typed. `rtGapWouldBe` shows why the
    # gap must be refused: the shifted instant would read back as a DIFFERENT time.
    assert data["rtSeoul"] == "2026-09-23 10:00"
    assert data["rtAfterJump"] == "2026-03-08 03:00"
    assert data["rtFoldNy"] == "2026-11-01 01:30"
    assert data["rtGapWouldBe"] == "2026-03-08 01:30"   # NOT "02:30" -> drift
    assert data["rtBadZone"] is None
    assert data["rtEmptyZone"] is None

    assert data["badZoneIso"] == ""
    assert data["emptyZoneIso"] == ""
    assert data["badDateIso"] == ""
    assert data["badTimeIso"] == ""
    assert data["emptyTimeIso"] == ""

    assert data["offsetSeoul"] == "+09:00"
    assert data["offsetNegative"] == "-05:00"
    assert data["offsetHalf"] == "+05:30"

    # a 201 without a USABLE appointment projection is never treated as saved.
    # So the four stable fields the canonical projection always returns are all
    # required: calendar_item_id, item_type == "appointment", title, date.
    assert data["created"]["status"] == "created"
    assert data["created"]["item"]["calendar_item_id"] == "item_apt_a"
    for name in (
        "createdEmptyItem",
        "createdNullItem",
        "createdArrayItem",
        "createdNoDate",
        "createdWrongType",
        "createdEmptyTitle",
        "createdEmptyId",
        "createdBadDate",
        "createdNoItem",
        "createdNotOk",
        "createdStringItem",
    ):
        assert data[name]["status"] == "unavailable", name
        assert data[name]["item"] is None, name
    assert data["nullBody"]["status"] == "unavailable"
    assert data["unauthorized"]["status"] == "unauthorized"
    assert data["invalid"]["status"] == "invalid"
    assert data["forbidden"]["status"] == "unavailable"
    assert data["noStore"]["status"] == "unavailable"
    assert data["server"]["status"] == "unavailable"
    assert data["statusKeys"] == {
        "created": "calendar-appointment-created",
        "invalid": "calendar-appointment-invalid",
        "unauthorized": "calendar-appointment-unauthorized",
        "unavailable": "calendar-appointment-unavailable",
    }


# ── server acceptance: the client payload is what the contract accepts ──


def _client_payloads() -> dict:
    """The exact request bodies the real client builds, produced by the client."""
    script = f"""
    global.window = {{}};
    require({json.dumps(str(CALENDAR_JS_PATH))});
    const ui = window.PadiemCalendarUI;
    const ok = (r) => r.payload;
    process.stdout.write(JSON.stringify({{
      dateOnly: ok(ui.buildAppointmentRequest({{ appointment_type: "date_only", title: "A사 계약", date: "2026-09-23" }})),
      allDay: ok(ui.buildAppointmentRequest({{ appointment_type: "all_day", title: "워크숍", date: "2026-10-01" }})),
      timed: ok(ui.buildAppointmentRequest({{ appointment_type: "timed", title: "회의", date: "2026-09-23", timezone: "Asia/Seoul", start_time: "10:00", end_time: "11:30", reminder_minutes: 30 }})),
      timedDst: ok(ui.buildAppointmentRequest({{ appointment_type: "timed", title: "베를린 콜", date: "2026-07-01", timezone: "Europe/Berlin", start_time: "12:00" }})),
      naive: {{ appointment_type: "timed", title: "회의", timezone: "Asia/Seoul", start_at: "2026-09-23T10:00:00" }},
      noZone: {{ appointment_type: "timed", title: "회의", start_at: "2026-09-23T10:00:00+09:00" }},
      gap: ui.zonedLocalToIso("2026-03-08", "02:30", "America/New_York"),
      gapDrift: {{ appointment_type: "timed", title: "DST 갭", timezone: "America/New_York", start_at: "2026-03-08T02:30:00-04:00" }},
      foldBuilt: ui.buildAppointmentRequest({{ appointment_type: "timed", title: "DST 폴드", date: "2026-11-01", timezone: "America/New_York", start_time: "01:30" }}).payload,
      gapWallClockOfDrift: ui.zoneWallClock("America/New_York", Date.parse("2026-03-08T02:30:00-04:00")),
    }}));
    """
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _create(payload: dict):
    """Feed a client body through the existing contract, route-style."""
    kwargs = dict(payload)
    kwargs["date_val"] = kwargs.pop("date", None)
    kwargs["tz_name"] = kwargs.pop("timezone", None)
    return CalendarAppointment.create(
        workspace_id="ws_a5", owner_id="owner_a5", **kwargs
    )


def test_client_payloads_are_accepted_by_the_existing_contract() -> None:
    payloads = _client_payloads()

    date_only = _create(payloads["dateOnly"])
    assert date_only.appointment_type is AppointmentType.DATE_ONLY
    assert date_only.date == date(2026, 9, 23)
    # No synthetic time and no zone is invented for a date-only appointment.
    assert date_only.start_at is None
    assert date_only.end_at is None
    assert date_only.timezone is None

    all_day = _create(payloads["allDay"])
    assert all_day.appointment_type is AppointmentType.ALL_DAY
    assert all_day.date == date(2026, 10, 1)
    assert all_day.start_at is None and all_day.end_at is None and all_day.timezone is None

    timed = _create(payloads["timed"])
    assert timed.appointment_type is AppointmentType.TIMED
    assert timed.timezone == "Asia/Seoul"
    assert timed.reminder_minutes == 30
    # The date the server derives in the explicit zone is the date the user picked.
    assert timed.date == date(2026, 9, 23)
    assert timed.start_at is not None and timed.start_at.tzinfo is not None
    assert timed.start_at.utcoffset() == timedelta(0)
    # 10:00 KST == 01:00 UTC, and the 90-minute span survives normalization.
    assert (timed.start_at.hour, timed.start_at.minute) == (1, 0)
    assert timed.end_at is not None
    assert timed.end_at - timed.start_at == timedelta(minutes=90)

    dst = _create(payloads["timedDst"])
    assert dst.date == date(2026, 7, 1)
    assert dst.timezone == "Europe/Berlin"
    # 12:00 CEST == 10:00 UTC (the client resolved +02:00, not +01:00).
    assert (dst.start_at.hour, dst.start_at.minute) == (10, 0)


def test_contract_rejects_the_shapes_this_client_never_builds() -> None:
    payloads = _client_payloads()
    # A naive start_at is rejected by the server, so the offset the client adds is
    # load-bearing: without it the request would be refused, never guessed at.
    with pytest.raises(CalendarContractError) as naive:
        _create(payloads["naive"])
    assert naive.value.code == "naive_datetime_rejected"
    # A timed appointment with no explicit zone is rejected as well.
    with pytest.raises(CalendarContractError) as no_zone:
        _create(payloads["noZone"])
    assert no_zone.value.code == "timezone_required"
    # And the client itself never emits either shape. Only the bodies the builder
    # produced are checked: "naive" and "noZone" above are hand-written inputs
    # used to prove the server would refuse them if they ever were produced.
    built_timed = [payloads["timed"], payloads["timedDst"]]
    for body in built_timed:
        assert body["appointment_type"] == "timed"
        assert body.get("timezone")
        assert OFFSET_SUFFIX.search(body["start_at"]), body
    # The two hand-written shapes differ from the built ones only by the offset
    # and the zone, i.e. exactly the two guarantees this client makes.
    assert payloads["naive"]["start_at"] == payloads["timed"]["start_at"][:-6]
    assert set(payloads["noZone"]) == {"appointment_type", "title", "start_at"}


def test_nonexistent_dst_wall_clock_is_never_built_and_would_be_drifted() -> None:
    payloads = _client_payloads()
    # New York jumps 02:00 -> 03:00 on 2026-03-08, so 02:30 does not exist there.
    # The client refuses it outright, before any request.
    assert payloads["gap"] == ""
    with pytest.raises(CalendarContractError) as gap:
        _create(
            {
                "appointment_type": "timed",
                "title": "DST 갭",
                "timezone": "America/New_York",
                "start_at": payloads["gap"],
            }
        )
    assert gap.value.code == "invalid_start_at"
    # Why refusal matters: the shifted-value shape the old converter produced is
    # timezone-aware, so the server ACCEPTS it — but its wall clock in the stated
    # zone is 01:30, not the 02:30 the user typed. Accepting it would have sent a
    # silently different instant.
    drifted = _create(payloads["gapDrift"])
    assert drifted.timezone == "America/New_York"
    assert payloads["gapWallClockOfDrift"] == "2026-03-08 01:30"
    # The ambiguous fall-back value the client DOES build stays inside the zone's
    # real wall clock and the server derives the same date in that zone.
    folded = _create(
        {
            "appointment_type": "timed",
            "title": "DST 폴드",
            "timezone": "America/New_York",
            "start_at": payloads["foldBuilt"]["start_at"],
        }
    )
    assert folded.timezone == "America/New_York"
    assert folded.start_at.isoformat() == "2026-11-01T05:30:00+00:00"
    assert folded.date == date(2026, 11, 1)


def test_this_slice_adds_no_external_calendar_or_memory_authority() -> None:
    assert EXTERNAL_CALENDAR_REQUIRED is False
    assert MEMORY_AUTO_PROMOTION is False
    source = _source().lower()
    for forbidden in (
        "googleapis",
        "oauth",
        "access_token",
        "refresh_token",
        "api_key",
        "client_secret",
        "bearer",
    ):
        assert forbidden not in source, forbidden


if __name__ == "__main__":
    test_index_declares_the_appointment_form_with_bounded_fields()
    test_appointment_type_selector_offers_the_three_contract_types_only()
    test_time_fields_are_bound_to_hideable_containers()
    test_appointment_form_lives_inside_the_calendar_view_not_the_chat_shell()
    test_appointment_status_region_is_an_announced_polite_status()
    test_help_copy_no_longer_denies_appointment_creation()
    test_hint_states_native_ownership_and_no_memory_promotion()
    test_timezone_note_discloses_the_no_inference_rule()
    test_locale_defines_every_appointment_key_for_ko_and_en()
    test_every_markup_locale_key_has_a_translation()
    test_write_target_is_the_existing_registered_appointment_authority()
    test_route_registers_workspace_and_owner_server_side_only()
    test_client_payload_keys_match_the_existing_route_contract()
    test_only_the_two_native_write_methods_exist_in_the_module()
    test_appointment_write_request_shape_is_json_same_origin_and_uncached()
    test_client_never_constructs_owner_workspace_or_tenant_scope()
    test_no_second_appointment_authority_or_reminder_scheduler()
    test_render_discipline_is_unchanged_for_the_appointment_path()
    test_appointment_form_styles_use_shared_tokens_only()
    test_behavioral_harness_passes()
    test_appointment_helpers_build_the_contract_payload_or_fail_closed()
    test_client_payloads_are_accepted_by_the_existing_contract()
    test_contract_rejects_the_shapes_this_client_never_builds()
    test_nonexistent_dst_wall_clock_is_never_built_and_would_be_drifted()
    test_this_slice_adds_no_external_calendar_or_memory_authority()
    print("B54_PADIEM_CALENDAR_APPOINTMENT_CREATE_UI_TESTS=PASS")
