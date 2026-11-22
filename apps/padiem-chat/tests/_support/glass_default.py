"""Parsed views for the #1363 glass-default contracts (#8060).

Raw served sheets stay behind this helper (via ``claw_static`` and the shared
conversation-search JS parser and ``css_rules``). Contract tests receive parsed
JS calls/assignments/returns and CSS rule facts, and assert on those instead of
pinning shipped source spelling. No runtime file is changed.
"""
from __future__ import annotations

import re
from collections import Counter

from css_rules import rules_for_sheet
from _support.claw_static import sheet
from _support.conversation_search_4471 import (
    _balanced_block,
    _executable,
    _facts,
    _string_literals,
)


_IDENT = r"[A-Za-z_$][\w$]*"
_CHAIN = rf"{_IDENT}(?:\.{_IDENT})*"
_ASSIGN_RX = re.compile(rf"\b({_CHAIN})\s*=(?!=)\s*([^;\n]+);")
_RETURN_RX = re.compile(r"\breturn\s+([^;\n]+);")
_FUNCTION_RX = re.compile(rf"\bfunction\s+({_IDENT})\s*\(")
_COMPARE_RX = re.compile(rf"({_CHAIN}\([^)]*\)|{_CHAIN}|{_IDENT})\s*(!==|===|!=|==)\s*([^\s;&|]+)")


def _norm(value: str) -> str:
    return " ".join(value.split())


def _clean_left(value: str) -> str:
    return value[3:] if value.startswith("if(") else value


def js_view(sheet_name: str) -> dict:
    text = _executable(sheet_name)
    facts = _facts(text)
    assignments = [(target, _norm(rhs)) for target, rhs in _ASSIGN_RX.findall(text)]
    facts.update({
        "string_literals": set(_string_literals(text)),
        "assignments": set(assignments),
        "returns": {_norm(value) for value in _RETURN_RX.findall(text)},
        "function_names": set(_FUNCTION_RX.findall(text)),
        "comparisons": {
            f"{_clean_left(left)}{op}{right.rstrip('){')}"
            for left, op, right in _COMPARE_RX.findall(text)
        },
        "call_counts": dict(Counter(facts["calls"])),
    })
    return facts


def handler_view(sheet_name: str, marker: str = "var handler=function") -> dict:
    """Parsed facts for the color-scheme change handler body."""
    text = _executable(sheet_name)
    start = text.index(marker)
    block = _balanced_block(text, text.index("{", start))
    facts = _facts(block)
    facts["calls"] = list(facts["calls"])
    return facts


def css_facts(sheet_name: str) -> dict:
    rules = rules_for_sheet(sheet_name)
    return {
        "rules": rules,
        "selectors": {selector for rule in rules for selector in rule.selectors},
        "declarations": {
            (prop, value) for rule in rules for prop, value in rule.declarations.items()
        },
    }


def index_script_refs() -> list[str]:
    from _support.html_tags import tags_for_page

    return [
        attrs["src"] for tag, attrs in tags_for_page("index.html")
        if tag == "script" and attrs.get("src")
    ]
