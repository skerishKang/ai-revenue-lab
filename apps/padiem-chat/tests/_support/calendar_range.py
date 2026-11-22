"""#8060 parsed facts for the day/week/month calendar range UI.

Raw reads of the shipped static files stay in this support module. Contract
tests assert parsed markup, parsed declarations and parsed source values, so
a spelling-only edit in a static file does not break them.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from css_rules import declaration

from _support.calendar_static import (
    calendar_rules,
    factory_source,
    index_tags,
    js_source,
    locale_keys,
    routes_source,
)

ROOT = Path(__file__).resolve().parents[2]

RANGE_TABS = ("today", "day", "week", "month", "upcoming")
RANGE_ELEMENT_IDS = (
    "calendarRangeNavigation", "calendarPreviousRange", "calendarRangeLabel",
    "calendarRangeToday", "calendarNextRange", "calendarPanel",
)
RANGE_LOCALE_KEYS = (
    "calendar-day", "calendar-week", "calendar-month", "calendar-empty-day",
    "calendar-empty-week", "calendar-empty-month", "calendar-previous-aria",
    "calendar-next-aria",
)
RANGE_STATUSES = ("loading", "empty", "error", "ready")


def range_tabs_in_markup() -> tuple[str, ...]:
    return tuple(sorted({attrs["data-calendar-tab"] for _, attrs in index_tags()
                         if "data-calendar-tab" in attrs}))


def element_ids_in_markup() -> frozenset[str]:
    return frozenset(attrs["id"] for _, attrs in index_tags() if "id" in attrs)


def _strip_comments(source: str) -> str:
    code = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"^\s*//.*$", "", code, flags=re.MULTILINE)


def _block(source: str, start: str, end: str) -> str:
    if start not in source:
        return ""
    rest = source.split(start, 1)[1]
    return rest.split(end, 1)[0] if end in rest else rest


def js_range_facts() -> dict:
    source = js_source()
    code = _strip_comments(source)
    read_block = _block(source, "if (isRangeTab(currentTab))", "function selectTab")
    query_block = _block(code, "function buildItemsQuery", "\n  }")
    return {
        "items_route": tuple(re.findall(r'const\s+ITEMS_ROUTE\s*=\s*"([^"]+)"', source)),
        "query_builder_present": "function buildItemsQuery" in code,
        "query_keys": tuple(key for key in ("timezone", "start_date", "end_date")
                            if key + "=" in query_block),
        "fetch_uses_items_query": bool(re.search(
            r"fetch\(`\$\{ITEMS_ROUTE\}\$\{buildItemsQuery\(", read_block)),
        "read_credentials": tuple(sorted(set(re.findall(
            r'credentials:\s*"([^"]+)"', read_block)))),
        "read_cache": tuple(sorted(set(re.findall(r'cache:\s*"([^"]+)"', read_block)))),
        "all_credentials": tuple(sorted(set(re.findall(
            r'credentials:\s*"([^"]+)"', source)))),
        "all_cache": tuple(sorted(set(re.findall(r'cache:\s*"([^"]+)"', source)))),
        "read_has_method": "method:" in read_block,
        "statuses": tuple(sorted(set(re.findall(r'setStatus\("([a-z]+)"\)', code)))),
        "browser_timezone_used": "browserTimezone()" in code,
        "local_date_in_zone_used": "localDateInZone(" in code,
        "timezone_guard_present": "if (!timezone)" in code,
        "locale_keys_used": tuple(sorted(set(re.findall(
            r'"(calendar-empty-[a-z]+)"', code)))),
        "renderable_filter_used": "filter(isRenderableItem)" in code,
        "write_method_calls": source.count("method: method"),
        "has_delete": 'method: "DELETE"' in source,
        "has_put": 'method === "PUT"' in source,
        "has_patch": bool(re.search(r"\bPATCH\b", source)),
        "scope_fields": tuple(field for field in
                              ("workspace_id", "owner_id", "tenant_id", "source_ref")
                              if field in source),
        "dom_sinks": tuple(sink for sink in
                           ("innerHTML", "insertAdjacentHTML", "outerHTML", "document.write")
                           if sink in source),
    }


def css_range_facts() -> dict:
    rules = calendar_rules()
    selectors = tuple(selector for rule in rules for selector in rule.selectors)
    overflow = tuple(value for rule in rules
                     if (value := declaration(rule, "overflow-x")) is not None)
    return {"selectors": selectors, "overflow_x": overflow}


def locale_range_keys() -> dict[str, frozenset[str]]:
    return {lang: frozenset(locale_keys(lang)) for lang in ("ko", "en")}


def registered_calendar_routes() -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    for node in ast.walk(ast.parse(factory_source())):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if name != "Route" or not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        methods: tuple[str, ...] = ()
        for keyword in node.keywords:
            if keyword.arg == "methods" and isinstance(keyword.value, (ast.List, ast.Tuple)):
                methods = tuple(element.value for element in keyword.value.elts
                                if isinstance(element, ast.Constant))
        result[node.args[0].value] = methods
    return result


def calendar_items_route_contract() -> dict:
    for node in ast.parse(routes_source()).body:
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == "calendar_items":
            literals = {child.value for child in ast.walk(node)
                        if isinstance(child, ast.Constant) and isinstance(child.value, str)}
            return {
                "defined": True,
                "query_params": tuple(name for name in ("start_date", "end_date")
                                      if name in literals),
            }
    return {"defined": False, "query_params": ()}
