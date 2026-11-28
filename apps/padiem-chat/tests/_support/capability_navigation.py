"""Parsed views for the #1732 capability-navigation contracts (#8060 54차).

Raw file access stays here (via the shared ``claw_static``, ``html_tags`` and
conversation-search JS helpers). Contract tests receive parsed values — JS
call/identifier/object facts, HTML element facts and server AST facts — and
assert on those instead of pinning shipped source spelling. No runtime file is
changed.
"""
from __future__ import annotations

import ast
import re
from collections import Counter

from _support.claw_static import server_source, sheet
from _support.app_factory_modules import FACTORY_MODULES
from _support.conversation_search_4471 import (
    _balanced_block,
    _executable,
    _facts,
    _function_block,
)
from _support.html_tags import tags_for_page


_IDENT = r"[A-Za-z_$][\w$]*"
_CHAIN = rf"{_IDENT}(?:\.{_IDENT})*"
_PAIR_RX = re.compile(rf'"?({_IDENT})"?\s*:\s*"([^"]+)"')
_STRING_PLUS_CALL_RX = re.compile(r'"([^"]+)"\s*\+\s*(' + _CHAIN + r"\([^)]*\))")
_CAP_KEYS = frozenset(
    {"web_tools_ready", "deep_research_ready", "auth_configured", "history_store_bound"}
)


# --- HTML -------------------------------------------------------------------


def index_buttons() -> dict[str, dict]:
    """Every id-bearing <button> in index.html, keyed by id, in document order."""
    return {
        attrs["id"]: dict(attrs)
        for tag, attrs in tags_for_page("index.html")
        if tag == "button" and attrs.get("id")
    }


def index_ids() -> list[str]:
    """All element ids in document order."""
    return [attrs["id"] for _tag, attrs in tags_for_page("index.html") if attrs.get("id")]


def index_script_attrs() -> list[dict]:
    """Attribute maps of every <script src=...> in document order."""
    return [
        dict(attrs)
        for tag, attrs in tags_for_page("index.html")
        if tag == "script" and attrs.get("src")
    ]


def index_document_position(id_or_class: str) -> int:
    """Position of the first element whose id or class token matches."""
    for position, (_tag, attrs) in enumerate(tags_for_page("index.html")):
        if attrs.get("id") == id_or_class or id_or_class in attrs.get("class", "").split():
            return position
    raise AssertionError(f"{id_or_class} not found in index.html")


# --- JS ---------------------------------------------------------------------


def _property_string_pairs(text: str) -> set[tuple[str, str]]:
    return set(_PAIR_RX.findall(text))


def _call_counts(calls: list[str]) -> dict[str, int]:
    return dict(Counter(calls))


def _fetch_first_args(facts: dict) -> set[str]:
    return {
        args.partition(",")[0].strip()
        for callee, args in facts["call_args"]
        if callee == "nativeFetch"
    }


def _extra_facts(facts: dict, text: str) -> dict:
    facts["property_pairs"] = _property_string_pairs(text)
    facts["property_names"] = set(re.findall(rf"\b({_IDENT})\s*:", text))
    facts["method_counts"] = dict(Counter(re.findall(r'\bmethod\s*:\s*"([^"]+)"', text)))
    facts["string_plus_calls"] = set(_STRING_PLUS_CALL_RX.findall(text))
    facts["fetch_first_args"] = _fetch_first_args(facts)
    facts["call_counts"] = _call_counts(facts["calls"])
    return facts


def source_view(sheet_name: str) -> dict:
    """Parsed facts for a whole executable static JS sheet."""
    text = _executable(sheet_name)
    return _extra_facts(_facts(text), text)


def function_view(sheet_name: str, name: str) -> dict:
    """Parsed facts for one named function body in a static JS sheet."""
    block = _function_block(_executable(sheet_name), name)
    return _extra_facts(_facts(block), block)


def _object_entries(block: str) -> dict[str, str]:
    """Top-level ``key: expression`` entries of a JS object literal."""
    start, end = block.index("{"), block.rindex("}")
    body = block[start + 1:end]
    parts: list[str] = []
    depth = 0
    quote = ""
    chunk = 0
    i = 0
    while i < len(body):
        ch = body[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "\"'`":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(body[chunk:i])
            chunk = i + 1
        i += 1
    parts.append(body[chunk:])
    entries: dict[str, str] = {}
    for part in parts:
        part = part.strip()
        if not part or ":" not in part:
            continue
        key, _, value = part.partition(":")
        normalized = " ".join(value.split())
        if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in "\"'":
            normalized = normalized[1:-1]
        entries[key.strip().strip('"\'')] = normalized
    return entries


def _frozen_object(sheet_name: str, function_name: str) -> dict[str, str]:
    block = _function_block(_executable(sheet_name), function_name)
    match = re.search(r"Object\.freeze\(\s*\{", block)
    if match is None:
        raise AssertionError(f"Object.freeze object not found in {function_name}")
    return _object_entries(_balanced_block(block, block.index("{", match.end() - 1)))


def deployment_projection() -> dict[str, str]:
    """The bounded deployment projection returned by projectDeployment()."""
    return _frozen_object("product-capabilities.js", "projectDeployment")


def const_expression(sheet_name: str, name: str) -> str | None:
    """Normalized right-hand side of a top-level ``const NAME = ...;``."""
    match = re.search(
        rf"\bconst\s+{re.escape(name)}\s*=\s*([^;]+);", _executable(sheet_name)
    )
    return " ".join(match.group(1).split()) if match else None


def tier_copy_by_lang() -> dict[str, dict[str, str]]:
    """TIER_COPY split by language: {lang: {key: copy}}."""
    text = _executable("product-capabilities.js")
    match = re.search(r"\bconst\s+TIER_COPY\s*=\s*Object\.freeze\(\s*\{", text)
    if match is None:
        raise AssertionError("TIER_COPY assignment not found")
    outer = _object_entries(_balanced_block(text, text.index("{", match.end() - 1)))
    result: dict[str, dict[str, str]] = {}
    for lang, value in outer.items():
        inner = re.search(r"Object\.freeze\(\s*\{", value)
        if inner is None:
            continue
        result[lang] = _object_entries(
            _balanced_block(value, value.index("{", inner.end() - 1))
        )
    return result


def search_sources_export() -> dict | None:
    """The frozen object published as ``window.PadiemSearchSources``."""
    text = _executable("search-sources.js")
    match = re.search(
        rf"window\.PadiemSearchSources\s*=\s*Object\.freeze\(\s*\{{", text
    )
    if match is None:
        return None
    block = _balanced_block(text, text.index("{", match.end() - 1))
    entries = _object_entries(block)
    return {"frozen": True, "keys": sorted(entries), "values": sorted(entries.values())}


# --- server AST -------------------------------------------------------------


def app_factory_facts() -> dict:
    """Route declarations and health capability entries across all factory owners."""
    routes: list[tuple[str, tuple[str, ...]]] = []
    entries: dict[str, str] = {}
    for module_name in FACTORY_MODULES:
        source = server_source(module_name)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                callee = node.func
                name = callee.id if isinstance(callee, ast.Name) else getattr(callee, "attr", None)
                if name == "Route" and node.args and isinstance(node.args[0], ast.Constant):
                    methods: list[str] = []
                    for keyword in node.keywords:
                        if keyword.arg == "methods" and isinstance(keyword.value, (ast.List, ast.Tuple)):
                            methods = [
                                item.value for item in keyword.value.elts
                                if isinstance(item, ast.Constant) and isinstance(item.value, str)
                            ]
                    routes.append((node.args[0].value, tuple(methods)))
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if (
                        isinstance(key, ast.Constant)
                        and isinstance(key.value, str)
                        and key.value in _CAP_KEYS
                    ):
                        segment = ast.get_source_segment(source, value) or ""
                        entries[key.value] = " ".join(segment.split())
    return {"routes": routes, "capability_entries": entries}
