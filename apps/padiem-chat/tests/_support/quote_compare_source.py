"""Parsed/tokenized views for the Claw quote-compare UI contracts (#8060 56차).

Raw file reads live here. Tests receive parsed HTML elements, tokenized JS
facts, parsed CSS rules and locale maps. Existing ``claw_static``, ``css_rules``,
``locale_bundle`` and ``settings_dialog_source`` helpers are reused for the
underlying reads and parsing.
"""
from __future__ import annotations

import re

import locale_bundle
from css_rules import declaration, find_rules_with_selector, rules_for_sheet

from _support.claw_static import sheet
from _support.settings_dialog_source import index_elements

_STRING_RX = re.compile(r'"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\'')
_IDENTIFIER_RX = re.compile(r"[A-Za-z_$][\w$]*")


# ------------------------------------------------------------------ index.html

def index_text() -> str:
    return sheet("index.html")


def index_ids() -> list[str]:
    return sorted({
        el.attrs["id"] for el in index_elements() if el.attrs.get("id")
    })


def has_locale_text(value: str) -> bool:
    return value in index_text()


# ------------------------------------------------------ claw-quote-compare.js

def module_text() -> str:
    return sheet("claw-quote-compare.js")


def module_lines() -> list[str]:
    """Whitespace-normalized source lines for code-shape checks."""
    return [re.sub(r"\s+", " ", line).strip() for line in module_text().splitlines()]


def module_has(fragment: str) -> bool:
    return any(fragment in line for line in module_lines())


def module_lacks(fragment: str) -> bool:
    return not module_has(fragment)


def module_strings() -> set[str]:
    return {double or single for double, single in _STRING_RX.findall(module_text())}


def module_identifiers() -> set[str]:
    return set(_IDENTIFIER_RX.findall(module_text()))


def module_const(name: str) -> str:
    match = re.search(
        rf"\bconst\s+{re.escape(name)}\s*=\s*([^;]+);", module_text()
    )
    if not match:
        raise AssertionError(f"const {name} is not declared in claw-quote-compare.js")
    return match.group(1).strip()


def module_qc_keys() -> set[str]:
    return set(re.findall(r'"(claw-qc-[^"]+)"\s*:', module_text()))


# ---------------------------------------------------------------------- CSS

def compare_rules():
    return rules_for_sheet("claw-quote-compare.css")


def workspace_rules():
    return rules_for_sheet("claw-workspace.css")


def rule_for(rules, selector: str):
    found = find_rules_with_selector(rules, selector)
    return found[0] if found else None


def rule_value(rules, selector: str, prop: str):
    rule = rule_for(rules, selector)
    return declaration(rule, prop) if rule is not None else None


def media_conditions(rules) -> set[str]:
    return {rule.media for rule in rules if rule.media}


def selectors_of(rules) -> set[str]:
    return {selector for rule in rules for selector in rule.selectors}


# -------------------------------------------------------------------- locale

def locale_map(lang: str) -> dict[str, str]:
    return dict(locale_bundle.keys(lang))
