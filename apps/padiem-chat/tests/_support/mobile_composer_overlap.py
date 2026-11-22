"""Parsed views for the #4647 mobile composer overlap contracts (#8060).

Raw served sheets stay behind this helper (via ``claw_static``, the shared
HTML/JS parsers and ``css_rules``). Contract tests receive parsed CSS selectors,
declarations, media rules and JS call/assignment facts, and assert on those
instead of pinning shipped source spelling. No runtime file is changed.
"""
from __future__ import annotations

import re

from css_rules import rules_for_sheet
from _support.conversation_search_4471 import _executable, _string_literals
from _support.html_tags import tags_for_page
from _support.owner_setup_page import js_facts as _base_js_facts


_CHAIN = r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*"
_ASSIGN_RX = re.compile(rf"\b({_CHAIN})\s*=(?!=)\s*([^;\n]+);")


def css_facts(sheet_name: str) -> dict:
    rules = rules_for_sheet(sheet_name)
    return {
        "rules": rules,
        "selectors": {selector for rule in rules for selector in rule.selectors},
        "declarations": {
            (prop, value) for rule in rules for prop, value in rule.declarations.items()
        },
    }


def css_media_declarations(sheet_name: str, media: str) -> set[tuple[str, str]]:
    return {
        (prop, value)
        for rule in rules_for_sheet(sheet_name) if rule.media == media
        for prop, value in rule.declarations.items()
    }


def js_view(sheet_name: str) -> dict:
    text = _executable(sheet_name)
    facts = _base_js_facts(text)
    facts["string_literals"] = set(_string_literals(text))
    pairs = [(target, " ".join(rhs.split())) for target, rhs in _ASSIGN_RX.findall(text)]
    facts["assignments_full"] = dict(pairs)
    facts["assignments_all"] = set(pairs)
    return facts


def const_expression(sheet_name: str, name: str) -> str | None:
    match = re.search(
        rf"\bconst\s+{re.escape(name)}\s*=\s*([^;]+);", _executable(sheet_name)
    )
    return " ".join(match.group(1).split()) if match else None


def index_assets() -> dict:
    tags = tags_for_page("index.html")
    return {
        "stylesheets": [attrs["href"] for tag, attrs in tags if tag == "link" and attrs.get("href")],
        "scripts": [attrs["src"] for tag, attrs in tags if tag == "script" and attrs.get("src")],
        "has_attr": {
            name for _tag, attrs in tags for name in attrs
        },
    }
