"""Parsed views for the automation page UX contracts (#8060).

Raw file reads live here. Tests receive parsed HTML ids/attributes, locale maps,
tokenized JS sources and parsed CSS rules. The shared ``claw_static``,
``locale_bundle``, ``css_rules`` and ``settings_dialog_source`` helpers are reused.
"""
from __future__ import annotations

import re

import locale_bundle
from css_rules import declaration, find_rules_with_selector, rules_for_sheet

from _support.claw_static import sheet
from _support.settings_dialog_source import by_id, index_elements

_STRING_RX = re.compile(r'"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\'')
_IDENTIFIER_RX = re.compile(r"[A-Za-z_$][\w$]*")


# -------------------------------------------------------------- index.html

def index_text() -> str:
    return sheet("index.html")


def index_ids() -> list[str]:
    return [el.attrs["id"] for el in index_elements() if el.attrs.get("id")]


def index_attrs(element_id: str) -> dict[str, str | None]:
    found = by_id(index_elements(), element_id)
    return found[0].attrs if found else {}


def _walk(elements):
    for el in elements:
        yield el
        yield from _walk(el.children)


def section_ids(section_id: str) -> list[str]:
    """Every id inside the section with the given id, in document order."""
    section = next(
        (el for el in index_elements() if el.attrs.get("id") == section_id), None
    )
    assert section is not None, f"section not found: {section_id}"
    return [
        el.attrs["id"]
        for el in _walk(section.children)
        if el.attrs.get("id")
    ]


# ----------------------------------------------------------------- locale

def locale_key_count(key: str) -> int:
    """Number of languages whose parsed locale map declares ``key``."""
    return sum(key in locale_bundle.keys(lang) for lang in ("ko", "en"))


# ---------------------------------------------------------------------- JS

def module_text(name: str) -> str:
    return sheet(name)


def combined_module_text(names) -> str:
    return "\n".join(module_text(name) for name in names)


def module_tokens(name: str) -> set[str]:
    source = module_text(name)
    identifiers = set(_IDENTIFIER_RX.findall(source))
    strings = {double or single for double, single in _STRING_RX.findall(source)}
    return identifiers | strings


def module_has(name: str, fragment: str) -> bool:
    return fragment in module_text(name)


def module_lacks(name: str, fragment: str) -> bool:
    return fragment not in module_text(name)


# --------------------------------------------------------------------- CSS

def views_rules():
    return rules_for_sheet("standalone-views.css")


def css_value(selector: str, prop: str):
    found = find_rules_with_selector(views_rules(), selector)
    return declaration(found[0], prop) if found else None


def css_has_selector(selector: str) -> bool:
    return bool(find_rules_with_selector(views_rules(), selector))


def css_has_value(token: str) -> bool:
    return any(
        token in value
        for rule in views_rules()
        for value in rule.declarations.values()
    )
