"""Parsed views for the composer computer-connection status (#8060).

Raw served sheets stay behind this helper (via the shared ``claw_static``,
``html_tags``, ``css_rules`` and conversation-search JS helpers). Contract tests
receive parsed JS calls/identifiers, index asset references and CSS rule facts,
and assert on those instead of pinning shipped source spelling. No runtime file
is changed.
"""
from __future__ import annotations

import re
from collections import Counter

from css_rules import rules_for_sheet
from _support.conversation_search_4471 import (
    _executable,
    _facts,
    _string_literals,
)


_IDENT = r"[A-Za-z_$][\w$]*"
_CHAIN = rf"{_IDENT}(?:\.{_IDENT})*"
_ASSIGN_RX = re.compile(rf"\b({_CHAIN})\s*=(?!=)\s*([^;\n]+);")
_PAIR_RX = re.compile(rf'"?({_IDENT})"?\s*:\s*"([^"]+)"')


def js_view(sheet_name: str) -> dict:
    """Parsed facts for an executable static JS sheet."""
    text = _executable(sheet_name)
    facts = _facts(text)
    facts["string_literals"] = set(_string_literals(text))
    facts["assignments_full"] = {
        target: " ".join(rhs.split()) for target, rhs in _ASSIGN_RX.findall(text)
    }
    facts["property_pairs"] = set(_PAIR_RX.findall(text))
    facts["property_names"] = set(re.findall(rf"\b({_IDENT})\s*:", text))
    facts["call_counts"] = dict(Counter(facts["calls"]))
    return facts


def index_asset_refs() -> dict[str, list[str]]:
    from _support.html_tags import tags_for_page

    refs: dict[str, list[str]] = {"stylesheets": [], "scripts": [], "ids": []}
    for tag, attrs in tags_for_page("index.html"):
        if tag == "link" and attrs.get("href"):
            refs["stylesheets"].append(attrs["href"])
        if tag == "script" and attrs.get("src"):
            refs["scripts"].append(attrs["src"])
        if attrs.get("id"):
            refs["ids"].append(attrs["id"])
    return refs


def css_view(sheet_name: str) -> dict:
    rules = rules_for_sheet(sheet_name)
    return {
        "selectors": {selector for rule in rules for selector in rule.selectors},
        "declarations": {
            (prop, value) for rule in rules for prop, value in rule.declarations.items()
        },
    }


def const_expression(sheet_name: str, name: str) -> str | None:
    match = re.search(
        rf"\bconst\s+{re.escape(name)}\s*=\s*([^;]+);", _executable(sheet_name)
    )
    return " ".join(match.group(1).split()) if match else None


