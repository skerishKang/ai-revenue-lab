"""Parsed facts from the shipped Calendar surface for UI contracts (#8060 4차).

The raw ``read_text`` calls live here so a contract test can assert on parsed
values instead of pinning source spelling. No runtime file or route changes.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

from css_rules import declaration, find_rules_with_selector, rules_for_sheet
import locale_bundle
from locale_bundle import keys as locale_keys_raw
from _support.html_tags import tags_for_page

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "static"
CALENDAR_JS = STATIC / "calendar.js"


class _TagsIn(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)


def tags_in(markup) -> list[tuple[str, dict[str, str]]]:
    parser = _TagsIn()
    parser.feed(markup)
    parser.close()
    return parser.tags


def index_markup() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


def index_tags() -> list[tuple[str, dict[str, str]]]:
    return tags_for_page("index.html")


def record_form_markup() -> str:
    html = index_markup()
    start = html.index('id="calendarRecord"')
    start = html.rindex("<details", 0, start)
    return html[start:].split("</details>", 1)[0] + "</details>"


def tags_with_id(tags, element_id):
    return [tag for tag in tags if tag[1].get("id") == element_id]


def calendar_rules():
    return rules_for_sheet("calendar.css")


def css_selectors(rules):
    return [selector for rule in rules for selector in rule.selectors]


def css_declaration(rules, selector, prop):
    matches = find_rules_with_selector(rules, selector)
    return [declaration(rule, prop) for rule in matches]


def locale_keys(lang):
    return locale_keys_raw(lang)


def js_source() -> str:
    return CALENDAR_JS.read_text(encoding="utf-8")


def _block(source, start_marker, end_marker):
    if start_marker not in source:
        return ""
    rest = source.split(start_marker, 1)[1]
    return rest.split(end_marker, 1)[0] if end_marker in rest else rest


def js_facts() -> dict:
    source = js_source()
    code = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    code = re.sub(r"^\s*//.*$", "", code, flags=re.MULTILINE)
    read_block = _block(source, "async function load(", "function selectTab(")
    write_block = _block(source, "async function submitRecord(event) {", "function selectTab(")
    builder = _block(code, "function buildWorkLogRequest(input) {", "\n  }")
    return {
        "route_declarations": re.findall(r'const\s+WORK_LOG_ROUTE\s*=\s*"([^"]+)"', source),
        "route_literal_count": source.count('"/api/calendar/work-logs"'),
        "appointment_route_count": source.count('"/api/calendar/appointments"'),
        "fetch_endpoint_present": "fetch(endpoint, {" in source,
        "write_method_calls": source.count("method: method"),
        "delete_present": 'method: "DELETE"' in source,
        "put_present": 'method === "PUT"' in source,
        "patch_present": bool(re.search(r"\bPATCH\b", source)),
        "read_has_method": "method:" in read_block,
        "write_credentials": re.findall(r'credentials:\s*"([^"]+)"', write_block),
        "write_cache": re.findall(r'cache:\s*"([^"]+)"', write_block),
        "content_type": [v for v in re.findall(r'"Content-Type":\s*"([^"]+)"', write_block)],
        "accept": re.findall(r'Accept:\s*"([^"]+)"', write_block),
        "body_expression": re.findall(r"body:\s*([^,\n]+)", write_block),
        "scope_fields": [field for field in
                         ("user_id", "workspace_id", "owner_id", "tenant_id", "member_id", "workspace")
                         if field in code],
        "payload_builder_fields": [key for key in ("date", "title", "content") if re.search(rf"\b{key}\s*:", builder)],
        "payload_mutations": re.findall(r"payload\.([A-Za-z_]+)\s*=", builder),
        "dom_sinks": [sink for sink in
                      ("innerHTML", "insertAdjacentHTML", "outerHTML", "document.write", "eval(")
                      if sink in source],
        "storage_apis": [api for api in ("localStorage", "sessionStorage") if api in source],
        "status_text_assignment": "recordStatus.textContent = text(key)" in source,
        "status_calls": re.findall(r"showRecordStatus\(", write_block),
        "status_region_element_ids": [r[1].get("id") for r in index_tags()
                                      if r[1].get("role") == "status"],
    }


def factory_source() -> str:
    from _support.app_factory_modules import factory_area_source
    return factory_area_source()


def app_js_source() -> str:
    return (STATIC / "app.js").read_text(encoding="utf-8")


def nav_module_source() -> str:
    return (STATIC / "chat-nav-module.js").read_text(encoding="utf-8")


def ui_facts() -> dict:
    source = js_source()
    read_block = _block(source, "async function load(", "function selectTab(")
    detail_block = _block(source, "async function loadItemDetail(", "function buildRow(")
    code = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    code = re.sub(r"^\s*//.*$", "", code, flags=re.MULTILINE)
    return {
        "endpoints": sorted({value.strip('"') for value in
                             re.findall(r'"/api/calendar/[a-z-]+"', source)}),
        "build_query_present": "buildQuery" in source,
        "query_timezone": "timezone=" in source,
        "browser_timezone": "browserTimezone" in source,
        "intl_timezone": "Intl.DateTimeFormat().resolvedOptions().timeZone" in source,
        "hardcoded_zone": "Asia/Seoul" in source,
        "fetch_credentials": sorted(set(re.findall(r'credentials:\s*"([^"]+)"', source))),
        "fetch_cache": sorted(set(re.findall(r'cache:\s*"([^"]+)"', source))),
        "read_has_method": "method:" in read_block,
        "fetch_route_template": "fetch(`${routeFor(currentTab)}${buildQuery(timezone)}`" in read_block,
        "write_method_calls": source.count("method: method"),
        "has_delete": 'method: "DELETE"' in source,
        "has_put": 'method === "PUT"' in source,
        "patch_present": bool(re.search(r"\bPATCH\b", source)),
        "statuses": sorted(set(re.findall(r'setStatus\("([a-z]+)"\)', source))),
        "element_ids": sorted(set(re.findall(r'getElementById\("([A-Za-z]+)"\)', source))),
        "retry_listener": 'retry.addEventListener("click", () => load())' in source,
        "request_token": "requestToken" in source,
        "retry_on_auth_or_server": bool(re.search(
            r"attempt < 1 && \(response\.status === 401 \|\| response\.status >= 500\)", source)),
        "retry_wait_ms": re.findall(r"await wait\((\d+)\);", source),
        "empty_path_present": bool(re.search(
            r'if \(items\.length === 0\) \{\s*list\.replaceChildren\(\);\s*setStatus\("empty"\);\s*return;', source)),
        "known_types": sorted(set(re.findall(r'"(work_log|appointment|task|alert|claw_run|automation_run)"', source))),
        "known_type_constant": "KNOWN_ITEM_TYPES" in source,
        "known_type_helper": "isKnownItemType" in source,
        "type_keys": sorted(set(re.findall(r'"(calendar-item-[a-z-]+)"', source))),
        "item_type_synthesis": "item_type:" in code,
        "dom_sinks": [sink for sink in
                      ("innerHTML", "insertAdjacentHTML", "outerHTML", "document.write", "eval(")
                      if sink in source],
        "anchor_creation": 'createElement("a")' in source,
        "href_usage": "href" in source,
        "storage_apis": [api for api in ("localStorage", "sessionStorage") if api in source],
        "public_export": "window.PadiemCalendarUI" in source,
        "frozen_export": "Object.freeze" in source,
        "node_guard": 'typeof document === "undefined"' in source,
        "source_type_text": "sourceTypeText" in source,
        "source_ref_fields": [field for field in ("source_ref", "sourceRef") if field in source],
        "source_type_guard": 'return typeof item.source_type === "string" ? item.source_type.trim() : "";' in source,
        "source_chip_guard": "if (sourceText) head.append(" in source,
        "item_detail_route": re.findall(r'const ITEM_DETAIL_ROUTE = "([^"]+)"', source),
        "detail_route_builder": "buildItemDetailRoute" in source,
        "detail_guard": "isRenderableDetail" in source,
        "link_back_guard": "isRenderableLinkBack" in source,
        "open_link_event": "padiem:calendar-open-link" in source,
        "link_back_fields": [f for f in ("link_backs", "target_id") if f in source],
        "detail_read_has_method": "method:" in detail_block,
        "detail_credentials": sorted(set(re.findall(r'credentials:\s*"([^"]+)"', detail_block))),
        "detail_cache": sorted(set(re.findall(r'cache:\s*"([^"]+)"', detail_block))),
    }


def locale_source_text():
    return locale_bundle.SOURCE.read_text(encoding="utf-8")


def appointment_form_markup():
    html = index_markup()
    start = html.index('id="calendarAppointment"')
    start = html.rindex("<details", 0, start)
    return html[start:].split("</details>", 1)[0] + "</details>"


def appointment_type_values(markup):
    block = markup.split('id="calendarAppointmentType"', 1)[1].split("</select>", 1)[0]
    return re.findall(r'<option value="([^"]+)"', block)


def routes_source():
    return (ROOT / "app/calendar_routes.py").read_text(encoding="utf-8")


def static_path(name):
    return str(STATIC / name)


def css_source_text():
    return (STATIC / "calendar.css").read_text(encoding="utf-8")
