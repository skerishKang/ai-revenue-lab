"""Parsed views for the #7173 util-tools contracts (#8060).

Raw served sheets stay behind this helper (via ``claw_static``, ``html_tags``,
``css_rules`` and the shared conversation-search JS parser). Contract tests
receive parsed JS calls/identifiers/regex/exports, index asset refs and CSS
rule facts, and assert on those instead of pinning shipped source spelling. No
runtime file is changed.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from css_rules import rules_for_sheet
from _support.claw_static import sheet
from _support.composer_pc_status import index_asset_refs
from _support.conversation_search_4471 import _executable, _string_literals
from _support.owner_setup_page import js_facts as _base_js_facts


_REPO = Path(__file__).resolve().parents[4]
_IDENT = r"[A-Za-z_$][\w$]*"
_CHAIN = rf"{_IDENT}(?:\.{_IDENT})*"
_ASSIGN_RX = re.compile(rf"\b({_CHAIN})\s*=(?!=)\s*([^;\n]+);")
_REGEX_RX = re.compile(r"/((?:\\.|[^/\\])+)/[gimsuy]*")
_STATUS_PLUS_RX = re.compile(r"\bstatus\s*\+")
_STATUS_TEMPLATE_RX = re.compile(r"\$\{[^}]*\bstatus\b[^}]*\}")


def _norm(value: str) -> str:
    return " ".join(value.split())


def js_view(sheet_name: str) -> dict:
    """Parsed facts for an executable static JS sheet."""
    text = _executable(sheet_name)
    facts = _base_js_facts(text)
    facts["string_literals"] = set(_string_literals(text))
    facts["assignments_full"] = {
        target: _norm(rhs) for target, rhs in _ASSIGN_RX.findall(text)
    }
    facts["regex_literals"] = set(_REGEX_RX.findall(text))
    facts["property_identifier_pairs"] = set(
        re.findall(rf"\b({_IDENT})\s*:\s*({_IDENT})\b", text)
    )
    facts["call_counts"] = dict(Counter(facts["calls"]))
    facts["line_count"] = text.count("\n") + 1
    return facts


def council_source() -> str:
    """The sibling council app sheet, read only inside this helper."""
    path = _REPO / "apps" / "padiem-council-apps" / "static" / "council-app.js"
    return path.read_text(encoding="utf-8")


def council_js_view() -> dict:
    from _support.owner_setup_page import js_facts

    return js_facts(council_source())


def index_refs() -> dict[str, list[str]]:
    return index_asset_refs()


def error_copy_facts(sheet_name: str) -> dict:
    """Whether the error path pads a status token into user-facing copy."""
    text = _executable(sheet_name)
    return {
        "status_concatenated": bool(_STATUS_PLUS_RX.search(text)),
        "status_in_template": bool(_STATUS_TEMPLATE_RX.search(text)),
    }


def css_facts(sheet_name: str) -> dict:
    rules = rules_for_sheet(sheet_name)
    declarations = {
        (prop, value) for rule in rules for prop, value in rule.declarations.items()
    }
    return {
        "rules": rules,
        "selectors": {selector for rule in rules for selector in rule.selectors},
        "declarations": declarations,
        "media": {rule.media for rule in rules if rule.media},
    }
