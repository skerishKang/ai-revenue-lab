"""#2834 A4 — Native Padiem Calendar work-record create UI contract tests.

A3 shipped a read-only Today/Upcoming surface while the native work-log write
authority (POST /api/calendar/work-logs, Phase A routes + Phase B-2 D1 store)
already existed and was tested. A4 wires that authority into the product surface
so a user can actually write a daily record, which is the product premise of
#2834. This slice adds no endpoint, no store and no authority:

    existing POST /api/calendar/work-logs  ->  A4 form  ->  existing Today view

Coverage:
- markup: form ids, required fields, bounded maxlength, locale bindings, the
  explicit disclosure container for the switch to a write-capable surface.
- copy: the help text is no longer a false "nothing can be created" claim, and
  the hint states there is no automatic long-term-memory promotion.
- source: exactly one write method, the single existing route, JSON + same-origin
  + no-store request shape, and no owner/workspace/tenant scope construction.
- behavior: a Node DOM-stub harness executes the real static/calendar.js, drives
  the real submit path, and asserts the exact request and every status branch.
"""

from __future__ import annotations
import locale_bundle

from functools import lru_cache

import json
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
INDEX_PATH = STATIC / "index.html"
CALENDAR_JS_PATH = STATIC / "calendar.js"
CALENDAR_CSS_PATH = STATIC / "calendar.css"
LOCALE_PATH = locale_bundle.SOURCE
APP_FACTORY_PATH = ROOT / "app" / "app_factory.py"

WORK_LOG_ROUTE = "/api/calendar/work-logs"

RECORD_LOCALE_KEYS = [
    "calendar-record-summary",
    "calendar-record-hint",
    "calendar-record-date",
    "calendar-record-title-label",
    "calendar-record-title-placeholder",
    "calendar-record-content-label",
    "calendar-record-submit",
    "calendar-record-created",
    "calendar-record-invalid",
    "calendar-record-unauthorized",
    "calendar-record-unavailable",
]

# Server bounds from calendar_contracts (MAX_TITLE_CHARS / MAX_CONTENT_CHARS).
MAX_TITLE_CHARS = 200
MAX_CONTENT_CHARS = 4_000


# ---- parsed-surface contracts (no raw source spelling in this file) ----

# ---- parsed-surface contracts (no raw source spelling in this file) ----

from _support.calendar_static import (  # noqa: E402
    calendar_rules, factory_source, index_markup, index_tags, js_facts,
    locale_keys, record_form_markup, tags_in,
)


def _form_ids():
    return [attrs.get("id") for _tag, attrs in tags_in(record_form_markup()) if attrs.get("id")]


def _form_inputs():
    return [attrs for tag, attrs in tags_in(record_form_markup())
            if tag in ("input", "textarea")]


def _form_locale_keys():
    return {attrs.get("data-locale-key") for _tag, attrs in tags_in(record_form_markup())
            if attrs.get("data-locale-key")}


def _form_locale_placeholders():
    return {attrs.get("data-locale-placeholder") for _tag, attrs in tags_in(record_form_markup())
            if attrs.get("data-locale-placeholder")}


def _status_tag_attrs():
    for _tag, attrs in tags_in(record_form_markup()):
        if attrs.get("id") == "calendarRecordStatus":
            return attrs
    return {}


def test_index_declares_the_native_record_form_with_bounded_fields() -> None:
    ids = set(_form_ids())
    for expected in ("calendarRecordForm", "calendarRecordDate", "calendarRecordTitle",
                     "calendarRecordContent", "calendarRecordSubmit", "calendarRecordStatus"):
        assert expected in ids, expected
    tags = tags_in(record_form_markup())
    assert tags and tags[0][0] == "details"
    assert any(tag == "summary" and attrs.get("class") == "calendar-record-summary"
               for tag, attrs in tags)
    assert any(tag == "button" and attrs.get("type") == "submit" for tag, attrs in tags)
    inputs = _form_inputs()
    by_id = {attrs.get("id"): attrs for attrs in inputs}
    assert by_id["calendarRecordDate"].get("type") == "date"
    assert "required" in by_id["calendarRecordDate"]
    assert by_id["calendarRecordTitle"].get("maxlength") == str(MAX_TITLE_CHARS)
    assert by_id["calendarRecordContent"].get("maxlength") == str(MAX_CONTENT_CHARS)
    assert "calendar-record-title-placeholder" in _form_locale_placeholders()
    for key in ("calendar-record-summary", "calendar-record-hint", "calendar-record-date",
                "calendar-record-title-label", "calendar-record-content-label",
                "calendar-record-submit"):
        assert key in _form_locale_keys(), key


def test_record_form_lives_inside_the_calendar_view_not_the_chat_shell() -> None:
    html = index_markup()
    view_start = html.index('id="calendarView"')
    view_end = html.index('<section class="conversation"')
    form_start = html.index('id="calendarRecordForm"')
    assert view_start < form_start < view_end
    ids = [attrs.get("id") for _tag, attrs in index_tags()]
    assert ids.count("composerForm") == 1


def test_record_status_region_is_an_announced_polite_status() -> None:
    attrs = _status_tag_attrs()
    assert attrs.get("role") == "status"
    assert attrs.get("aria-live") == "polite"
    assert "hidden" in attrs


def test_help_copy_no_longer_denies_the_create_capability() -> None:
    ko = locale_keys("ko").get("calendar-help", "")
    en = locale_keys("en").get("calendar-help", "")
    assert ko and en
    for stale in ("읽기 전용", "만들거나 수정하지 않습니다", "read-only", "Nothing can be created"):
        assert stale not in ko + " " + en, stale
    assert "일정(예약)" in ko and "지원하지 않습니다" in ko
    assert "appointments" in en and "not supported" in en
    fallback = re.search(r'data-locale-key="calendar-help">([^<]*)</p>', index_markup())
    assert fallback is not None and fallback.group(1) == ko


def test_record_hint_states_no_automatic_memory_promotion() -> None:
    ko = locale_keys("ko").get("calendar-record-hint", "")
    en = locale_keys("en").get("calendar-record-hint", "")
    assert ko and en
    assert "기억" in ko and "자동" in ko
    assert "memory" in en and "not" in en
    for copy in (ko, en):
        assert "저장" not in copy or "자동" in copy


def test_locale_defines_every_record_key_for_ko_and_en() -> None:
    ko, en = locale_keys("ko"), locale_keys("en")
    for key in RECORD_LOCALE_KEYS:
        assert ko.get(key) and en.get(key), key


def test_write_target_is_the_existing_registered_work_log_authority() -> None:
    facts = js_facts()
    assert facts["route_declarations"] == [WORK_LOG_ROUTE]
    assert facts["fetch_endpoint_present"] is True
    assert facts["route_literal_count"] == 1
    assert f'Route("{WORK_LOG_ROUTE}", calendar_work_logs_create, methods=["POST"])' in factory_source()


def test_only_the_two_native_write_methods_exist_in_the_module() -> None:
    facts = js_facts()
    assert facts["write_method_calls"] == 2
    assert facts["route_literal_count"] == 1
    assert facts["appointment_route_count"] == 1
    assert facts["delete_present"] is True and facts["put_present"] is True
    assert facts["patch_present"] is False
    assert facts["read_has_method"] is False


def test_write_request_shape_is_json_same_origin_and_uncached() -> None:
    facts = js_facts()
    assert set(facts["write_credentials"]) == {"same-origin"}
    assert set(facts["write_cache"]) == {"no-store"}
    assert set(facts["content_type"]) == {"application/json"}
    assert set(facts["accept"]) == {"application/json"}
    assert facts["body_expression"] and {v.strip() for v in facts["body_expression"]} == {"JSON.stringify(built.payload)"}


def test_client_never_constructs_owner_workspace_or_tenant_scope() -> None:
    facts = js_facts()
    assert facts["scope_fields"] == []
    assert facts["payload_builder_fields"] == ["date", "title"]
    assert facts["payload_mutations"] == ["content"]


def test_render_discipline_is_unchanged_for_the_write_path() -> None:
    facts = js_facts()
    assert facts["dom_sinks"] == []
    assert facts["storage_apis"] == []
    assert len(facts["status_calls"]) >= 1
    assert facts["status_text_assignment"] is True


def test_record_form_styles_use_shared_tokens_only() -> None:
    rules = calendar_rules()
    selectors = [selector for rule in rules for selector in rule.selectors]
    for expected in (".calendar-record-form", ".calendar-record-status"):
        assert expected in selectors, expected
    assert any('data-record-status="created"' in selector for selector in selectors)
    values = [value for rule in rules for value in rule.declarations.values() if value]
    assert any("var(--accent-strong" in value for value in values)
    assert any("var(--line" in value for value in values)


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
  return el;
}

const byId = {};
ids.forEach((id) => { const e = makeEl("div"); e.id = id; byId[id] = e; });
byId.calendarRecordSubmit.disabled = false;

const shell = makeEl("div");
shell.dataset = { state: "home" };

const requests = [];
let mode = "created";
function json(status, body) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}
async function fetchImpl(url, opts) {
  opts = opts || {};
  const method = String(opts.method || "GET").toUpperCase();
  requests.push({
    url: String(url), method, headers: opts.headers || {},
    body: opts.body, credentials: opts.credentials, cache: opts.cache,
  });
  const u = String(url);
  if (u.startsWith("/api/calendar/work-logs") && method === "POST") {
    if (mode === "created") return json(201, { ok: true, work_log: { calendar_item_id: "item_log_x", item_type: "work_log" } });
    if (mode === "unauthorized") return json(401, { ok: false, error: { code: "unauthorized" } });
    if (mode === "invalid") return json(400, { ok: false, error: { code: "title_required" } });
    if (mode === "malformed") return json(201, { ok: true });
    return json(500, { ok: false, error: { code: "work_log_creation_failed" } });
  }
  if (u.startsWith("/api/calendar/items?")) return json(200, { ok: true, projection: { items: [] } });
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
  document: doc,
  fetch: fetchImpl,
  console,
  Intl,
  Date,
  JSON,
  Number,
  Object,
  String,
  Array,
  RegExp,
  Promise,
  setTimeout,
  clearTimeout,
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
  const dateField = byId.calendarRecordDate;
  const titleField = byId.calendarRecordTitle;
  const contentField = byId.calendarRecordContent;
  const submitButton = byId.calendarRecordSubmit;
  const status = byId.calendarRecordStatus;
  const form = byId.calendarRecordForm;

  function submit() {
    const event = { preventDefault() {} };
    return Promise.all((form.listeners.submit || []).map((fn) => fn(event)));
  }

  // 1) Opening the calendar performs the existing read-only load only.
  byId.calendarNavButton.click();
  await tick();
  await tick();
  checks.OPEN_LOADS_TODAY_ONLY =
    requests.length === 1 &&
    requests[0].method === "GET" &&
    requests[0].url.indexOf("/api/calendar/items?timezone=") === 0 &&
    shell.dataset.state === "calendar";
  if (!checks.OPEN_LOADS_TODAY_ONLY) fail("OPEN_LOADS_TODAY_ONLY " + JSON.stringify(requests));
  checks.DATE_DEFAULT_IS_EXPLICIT_ZONE_TODAY =
    /^\d{4}-\d{2}-\d{2}$/.test(dateField.value) &&
    dateField.value === sandbox.window.PadiemCalendarUI.localDateInZone(
      sandbox.window.PadiemCalendarUI.browserTimezone()
    );
  if (!checks.DATE_DEFAULT_IS_EXPLICIT_ZONE_TODAY) fail("DATE_DEFAULT " + dateField.value);

  // 2) A successful create posts exactly one bounded JSON body, then reloads.
  const before = requests.length;
  dateField.value = "2026-09-23";
  titleField.value = "   A사와 납기 협의함   ";
  contentField.value = "";
  await submit();
  await tick();
  const created = requests.slice(before);
  const post = created.find((r) => r.method === "POST");
  checks.WRITE_POSTS_ONCE_TO_THE_EXISTING_ROUTE =
    created.filter((r) => r.method === "POST").length === 1 &&
    !!post &&
    post.url === "/api/calendar/work-logs" &&
    post.credentials === "same-origin" &&
    post.cache === "no-store" &&
    post.headers["Content-Type"] === "application/json";
  if (!checks.WRITE_POSTS_ONCE_TO_THE_EXISTING_ROUTE) fail("WRITE_SHAPE " + JSON.stringify(created));
  const body = JSON.parse(post.body);
  checks.WRITE_BODY_IS_BOUNDED_AND_TRIMMED =
    JSON.stringify(Object.keys(body).sort()) === JSON.stringify(["date", "title"]) &&
    body.date === "2026-09-23" &&
    body.title === "A사와 납기 협의함";
  if (!checks.WRITE_BODY_IS_BOUNDED_AND_TRIMMED) fail("WRITE_BODY " + JSON.stringify(body));
  checks.WRITE_TRIGGERS_A_READ_REFRESH = created.some((r) => r.method === "GET" && r.url.indexOf("/api/calendar/items") === 0);
  if (!checks.WRITE_TRIGGERS_A_READ_REFRESH) fail("NO_REFRESH " + JSON.stringify(created));
  checks.SUCCESS_CONFIRMATION_IS_TEXT_AND_FIELDS_CLEAR =
    status.textContent === "T:calendar-record-created" &&
    status.hidden === false &&
    titleField.value === "" &&
    contentField.value === "";
  if (!checks.SUCCESS_CONFIRMATION_IS_TEXT_AND_FIELDS_CLEAR) {
    fail("SUCCESS_STATE " + JSON.stringify({ text: status.textContent, hidden: status.hidden, title: titleField.value }));
  }

  // 3) Optional content is sent only when present.
  const beforeContent = requests.length;
  titleField.value = "메모 있는 기록";
  contentField.value = "  견적 비교 완료  ";
  await submit();
  await tick();
  const withContent = JSON.parse(requests.slice(beforeContent).find((r) => r.method === "POST").body);
  checks.OPTIONAL_CONTENT_IS_TRIMMED_AND_SENT =
    withContent.content === "견적 비교 완료" && Object.keys(withContent).length === 3;
  if (!checks.OPTIONAL_CONTENT_IS_TRIMMED_AND_SENT) fail("CONTENT " + JSON.stringify(withContent));

  // 4) Every failure branch maps to a bounded message and never claims success.
  async function failureCase(nextMode, text, expectNoRequest) {
    mode = nextMode;
    titleField.value = "상태 확인";
    contentField.value = "";
    const count = requests.length;
    await submit();
    await tick();
    checks["FAILURE_" + nextMode.toUpperCase()] =
      status.textContent === "T:" + text &&
      (!expectNoRequest || requests.length === count);
    if (!checks["FAILURE_" + nextMode.toUpperCase()]) {
      fail("FAILURE_" + nextMode + " " + JSON.stringify({ text: status.textContent, added: requests.slice(count) }));
    }
  }
  await failureCase("unauthorized", "calendar-record-unauthorized", false);
  await failureCase("invalid", "calendar-record-invalid", false);
  await failureCase("server_error", "calendar-record-unavailable", false);
  await failureCase("malformed", "calendar-record-unavailable", false);

  // 5) Client-side rejection happens before any request is issued.
  mode = "created";
  const countBlank = requests.length;
  titleField.value = "   ";
  await submit();
  await tick();
  checks.BLANK_TITLE_IS_REJECTED_WITHOUT_A_REQUEST =
    status.textContent === "T:calendar-record-invalid" && requests.length === countBlank;
  if (!checks.BLANK_TITLE_IS_REJECTED_WITHOUT_A_REQUEST) fail("BLANK_TITLE " + JSON.stringify(requests.slice(countBlank)));
  const countBadDate = requests.length;
  titleField.value = "날짜 확인";
  dateField.value = "2026/09/23";
  await submit();
  await tick();
  checks.MALFORMED_DATE_IS_REJECTED_WITHOUT_A_REQUEST =
    status.textContent === "T:calendar-record-invalid" && requests.length === countBadDate;
  if (!checks.MALFORMED_DATE_IS_REJECTED_WITHOUT_A_REQUEST) fail("BAD_DATE " + JSON.stringify(requests.slice(countBadDate)));

  // 6) The whole journey stayed inside the three existing calendar routes.
  const allowed = ["/api/calendar/items", "/api/calendar/today", "/api/calendar/upcoming", "/api/calendar/work-logs"];
  const methods = Array.from(new Set(requests.map((r) => r.method))).sort();
  checks.NO_UNKNOWN_ROUTE_AND_NO_OTHER_METHOD =
    requests.every((r) => allowed.some((prefix) => r.url.indexOf(prefix) === 0)) &&
    JSON.stringify(methods) === JSON.stringify(["GET", "POST"]);
  if (!checks.NO_UNKNOWN_ROUTE_AND_NO_OTHER_METHOD) fail("ROUTES " + JSON.stringify({ methods, urls: requests.map((r) => r.url) }));
  checks.EVERY_WRITE_BODY_AVOIDS_SCOPE_FIELDS = requests
    .filter((r) => r.method === "POST")
    .every((r) => {
      const keys = Object.keys(JSON.parse(r.body));
      return keys.every((k) => ["date", "title", "content"].indexOf(k) >= 0);
    });
  if (!checks.EVERY_WRITE_BODY_AVOIDS_SCOPE_FIELDS) fail("SCOPE_LEAK " + JSON.stringify(requests.filter((r) => r.method === "POST")));

  console.log(JSON.stringify({ ok: true, checks, requests: requests.length }));
  process.exit(0);
})().catch((e) => {
  console.log(JSON.stringify({ ok: false, error: String((e && e.stack) || e) }));
  process.exit(0);
});
"""


# Every named consumer checks immutable fields from the same real app.js
# behavioral journey. Cache only within this process; never share across CI runs.
@lru_cache(maxsize=1)
def _run_harness() -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required for the behavioral harness"
    harness_path = ROOT / "tests" / "_calendar_ui_work_log_create_harness.js"
    harness_path.write_text(_HARNESS, encoding="utf-8")
    try:
        completed = subprocess.run(
            [node, str(harness_path), str(CALENDAR_JS_PATH), str(INDEX_PATH)],
            capture_output=True,
            text=True, encoding="utf-8",
            timeout=180,
        )
    finally:
        harness_path.unlink(missing_ok=True)
    assert completed.returncode == 0, f"harness exited {completed.returncode}: {completed.stderr}"
    line = completed.stdout.strip().splitlines()[-1] if completed.stdout.strip() else "{}"
    return json.loads(line)


def test_behavioral_harness_passes() -> None:
    payload = _run_harness()
    assert payload.get("ok") is True, payload


def test_behavioral_create_path_is_exactly_one_bounded_write() -> None:
    payload = _run_harness()
    assert payload.get("ok") is True, payload
    for name in (
        "OPEN_LOADS_TODAY_ONLY",
        "DATE_DEFAULT_IS_EXPLICIT_ZONE_TODAY",
        "WRITE_POSTS_ONCE_TO_THE_EXISTING_ROUTE",
        "WRITE_BODY_IS_BOUNDED_AND_TRIMMED",
        "WRITE_TRIGGERS_A_READ_REFRESH",
        "SUCCESS_CONFIRMATION_IS_TEXT_AND_FIELDS_CLEAR",
        "OPTIONAL_CONTENT_IS_TRIMMED_AND_SENT",
        "FAILURE_UNAUTHORIZED",
        "FAILURE_INVALID",
        "FAILURE_SERVER_ERROR",
        "FAILURE_MALFORMED",
        "BLANK_TITLE_IS_REJECTED_WITHOUT_A_REQUEST",
        "MALFORMED_DATE_IS_REJECTED_WITHOUT_A_REQUEST",
        "NO_UNKNOWN_ROUTE_AND_NO_OTHER_METHOD",
        "EVERY_WRITE_BODY_AVOIDS_SCOPE_FIELDS",
    ):
        assert payload["checks"].get(name) is True, name


# ── pure helper contracts (Node) ─────────────────────────────────────────


def test_pure_work_log_helpers_fail_closed() -> None:
    script = f"""
    global.window = {{}};
    require({json.dumps(str(CALENDAR_JS_PATH))});
    const ui = window.PadiemCalendarUI;
    const built = ui.buildWorkLogRequest({{ date: "2026-09-23", title: "  x  ", content: " " }});
    const keys = built.ok ? Object.keys(built.payload).sort() : [];
    process.stdout.write(JSON.stringify({{
      route: ui.WORK_LOG_ROUTE,
      okKeys: keys,
      titleTrimmed: built.payload ? built.payload.title : null,
      missingDate: ui.buildWorkLogRequest({{ title: "x" }}),
      badDate: ui.buildWorkLogRequest({{ date: "2026/09/23", title: "x" }}),
      dateTime: ui.buildWorkLogRequest({{ date: "2026-09-23T10:00:00Z", title: "x" }}),
      emptyTitle: ui.buildWorkLogRequest({{ date: "2026-09-23", title: "   " }}),
      nonString: ui.buildWorkLogRequest(null),
      created: ui.interpretWorkLogResponse(201, {{ ok: true, work_log: {{ calendar_item_id: "i" }} }}),
      createdNoBody: ui.interpretWorkLogResponse(201, {{ ok: true }}),
      unauthorized: ui.interpretWorkLogResponse(401, {{}}),
      invalid: ui.interpretWorkLogResponse(400, {{}}),
      forbidden: ui.interpretWorkLogResponse(403, {{}}),
      server: ui.interpretWorkLogResponse(500, {{}}),
      nullBody: ui.interpretWorkLogResponse(201, null),
      zoneDate: ui.localDateInZone("Asia/Seoul", new Date("2026-09-23T15:30:00Z")),
      zoneDateNextDay: ui.localDateInZone("Europe/Berlin", new Date("2026-09-23T22:30:00Z")),
      emptyZone: ui.localDateInZone("", new Date("2026-09-23T15:30:00Z")),
      badZone: ui.localDateInZone("Not/AZone", new Date("2026-09-23T15:30:00Z")),
      statusValues: ui.RECORD_STATUS_VALUES,
    }}));
    """
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True, encoding="utf-8",
    )
    data = json.loads(completed.stdout)
    assert data["route"] == WORK_LOG_ROUTE
    assert data["okKeys"] == ["date", "title"]
    assert data["titleTrimmed"] == "x"
    assert data["missingDate"] == {"ok": False, "reason": "invalid_date"}
    assert data["badDate"] == {"ok": False, "reason": "invalid_date"}
    assert data["dateTime"] == {"ok": False, "reason": "invalid_date"}
    assert data["emptyTitle"] == {"ok": False, "reason": "title_required"}
    assert data["nonString"] == {"ok": False, "reason": "invalid_date"}
    assert data["created"]["status"] == "created"
    assert data["createdNoBody"]["status"] == "unavailable"
    assert data["unauthorized"]["status"] == "unauthorized"
    assert data["invalid"]["status"] == "invalid"
    assert data["forbidden"]["status"] == "unavailable"
    assert data["server"]["status"] == "unavailable"
    assert data["nullBody"]["status"] == "unavailable"
    assert data["zoneDate"] == "2026-09-24"
    assert data["zoneDateNextDay"] == "2026-09-24"
    assert data["emptyZone"] == ""
    assert data["badZone"] == ""
    assert data["statusValues"] == ["created", "invalid", "unauthorized", "unavailable"]


if __name__ == "__main__":
    test_index_declares_the_native_record_form_with_bounded_fields()
    test_record_form_lives_inside_the_calendar_view_not_the_chat_shell()
    test_record_status_region_is_an_announced_polite_status()
    test_help_copy_no_longer_denies_the_create_capability()
    test_record_hint_states_no_automatic_memory_promotion()
    test_locale_defines_every_record_key_for_ko_and_en()
    test_write_target_is_the_existing_registered_work_log_authority()
    test_only_one_write_method_exists_in_the_module()
    test_write_request_shape_is_json_same_origin_and_uncached()
    test_client_never_constructs_owner_workspace_or_tenant_scope()
    test_render_discipline_is_unchanged_for_the_write_path()
    test_record_form_styles_use_shared_tokens_only()
    test_behavioral_harness_passes()
    test_behavioral_create_path_is_exactly_one_bounded_write()
    test_pure_work_log_helpers_fail_closed()
    print("B54_PADIEM_CALENDAR_WORK_LOG_CREATE_UI_TESTS=PASS")
