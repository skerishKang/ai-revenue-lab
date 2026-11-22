"""Parsed views for the #3790 verified model-choice contracts (#8060).

Raw served sheets stay behind this helper (via ``claw_static``, ``html_tags``
and the shared conversation-search JS parser). Contract tests receive parsed
JS calls/comparisons, HTML ids and server AST facts, and assert on those instead
of pinning shipped source spelling. No runtime file is changed.
"""
from __future__ import annotations

import ast
import functools
import re

from _support.claw_static import server_source
from _support.conversation_search_4471 import _executable, _string_literals
from _support.owner_setup_page import js_facts as _base_js_facts


_CHAIN = r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*"
_ASSIGN_RX = re.compile(rf"\b({_CHAIN})\s*=(?!=)\s*([^;\n]+);")
_TIER_GUARD_RX = re.compile(r"data\.tier\s*===\s*tier")
_AVAILABLE_BOOL_RX = re.compile(r'typeof\s+data\.available\s*===\s*"boolean"')


def _norm(value: str) -> str:
    return " ".join(value.split())


# #7801: these facts re-parsed the same shipped source on every call
# (app.js is ~10k lines; a contract file issues a dozen fact calls).
# Cache the parse per sheet/module; hand callers fresh copies so a
# caller mutating a set cannot pollute the next reader.
@functools.lru_cache(maxsize=None)
def _js_view_cached(sheet_name: str) -> dict:
    text = _executable(sheet_name)
    facts = _base_js_facts(text)
    facts["assignments_full"] = {
        target: _norm(rhs) for target, rhs in _ASSIGN_RX.findall(text)
    }
    facts["string_literals"] = set(_string_literals(text))
    return facts


def js_view(sheet_name: str) -> dict:
    """Parsed facts for an executable static JS sheet."""
    facts = _js_view_cached(sheet_name)
    return {**facts, "string_literals": set(facts["string_literals"])}


@functools.lru_cache(maxsize=None)
def choice_guard_facts(sheet_name: str) -> dict:
    """The two structural checks in the chooser's read-only status guard."""
    text = _executable(sheet_name)
    return {
        "tier_matches_query": bool(_TIER_GUARD_RX.search(text)),
        "available_is_boolean": bool(_AVAILABLE_BOOL_RX.search(text)),
    }


@functools.lru_cache(maxsize=None)
def _index_ids_and_scripts_cached() -> dict[str, list[str]]:
    from _support.html_tags import tags_for_page

    tags = tags_for_page("index.html")
    return {
        "ids": [attrs["id"] for _tag, attrs in tags if attrs.get("id")],
        "scripts": [attrs["src"] for tag, attrs in tags if tag == "script" and attrs.get("src")],
    }


def index_ids_and_scripts() -> dict[str, list[str]]:
    facts = _index_ids_and_scripts_cached()
    return {key: list(value) for key, value in facts.items()}


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


@functools.lru_cache(maxsize=None)
def _server_facts_cached(module_name: str) -> dict:
    """AST facts for one shipped server module."""
    source = server_source(module_name)
    tree = ast.parse(source)
    facts: dict[str, set] = {
        "calls": set(),
        "assignments": set(),
        "comparisons": set(),
        "if_conditions": set(),
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            args = ", ".join(_norm(ast.get_source_segment(source, arg) or "") for arg in node.args)
            facts["calls"].add((_call_name(node), args))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                value = node.value
                if isinstance(value, ast.Await):
                    value = value.value
                if isinstance(value, ast.Call):
                    rendered = f"{_call_name(value)}(...)"
                else:
                    rendered = _norm(ast.get_source_segment(source, value) or "")
                facts["assignments"].add((target.id, rendered))
        elif isinstance(node, ast.Compare):
            facts["comparisons"].add(_norm(ast.get_source_segment(source, node) or ""))
        elif isinstance(node, ast.If):
            facts["if_conditions"].add(_norm(ast.get_source_segment(source, node.test) or ""))
    return facts


def server_facts(module_name: str) -> dict:
    facts = _server_facts_cached(module_name)
    return {key: set(value) for key, value in facts.items()}
