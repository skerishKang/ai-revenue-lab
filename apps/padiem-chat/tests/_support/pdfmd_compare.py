"""Parsed views for the #7834 PDF→MD compare-view contracts (#8060 57차).

Raw file access stays here (via the shared ``claw_static`` sheet helper, the
conversation-search JS parser and ``css_rules``). Contract tests receive parsed
JS calls/assignments/early returns, string literals and CSS rule facts, and
assert on those instead of pinning shipped source spelling. No runtime file is
changed.
"""
from __future__ import annotations

import re

from css_rules import rules_for_sheet
from _support.conversation_search_4471 import (
    _executable,
    _facts,
    _function_block,
    _string_literals,
)


_IDENT = r"[A-Za-z_$][\w$]*"
_CHAIN = rf"{_IDENT}(?:\.{_IDENT})*"
_ASSIGN_RX = re.compile(rf"\b({_CHAIN})\s*=(?!=)\s*([^;\n]+);")
_EARLY_RETURN_RX = re.compile(r"\bif\s*\(\s*([^;{}\n]+?)\s*\)\s*return\s*;")
_PAIR_RX = re.compile(rf'"?({_IDENT})"?\s*:\s*"?({_CHAIN})"?')


def js_view(sheet_name: str) -> dict:
    """Parsed facts for an executable static JS sheet."""
    text = _executable(sheet_name)
    facts = _facts(text)
    facts["assignments_full"] = {
        target: " ".join(rhs.split()) for target, rhs in _ASSIGN_RX.findall(text)
    }
    facts["early_returns"] = [
        " ".join(condition.split())
        for condition in _EARLY_RETURN_RX.findall(text)
    ]
    facts["property_pairs"] = set(_PAIR_RX.findall(text))
    facts["property_names"] = set(re.findall(rf"\b({_IDENT})\s*:", text))
    return facts


def failed_branch_facts() -> dict:
    """Parsed facts inside the failed-item card branch of util-pdfmd.js."""
    text = _executable("util-pdfmd.js")
    start = text.index('if (item.status === "failed") {')
    end = text.index("list.appendChild(card);", start)
    block = text[start:end]
    facts = _facts(block)
    facts["string_literals"] = set(_string_literals(block))
    return facts


def delete_button_literals() -> set[str]:
    """String literals owned by the deleteButton() helper itself."""
    block = _function_block(_executable("util-pdfmd.js"), "deleteButton")
    return set(_string_literals(block))


def css_view(sheet_name: str) -> dict:
    """Selector and declaration facts for a shipped stylesheet."""
    rules = rules_for_sheet(sheet_name)
    return {
        "selectors": {selector for rule in rules for selector in rule.selectors},
        "declarations": {
            (prop, value) for rule in rules for prop, value in rule.declarations.items()
        },
    }
