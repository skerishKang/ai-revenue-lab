"""Parsed/tokenized views for the sidebar mode/profile contracts (#8060 62차).

Raw file reads live here. Tests receive tokenized JS sources, parsed CSS rules,
parsed HTML ids and locale maps. The shared ``claw_static``, ``css_rules``,
``locale_bundle`` and ``settings_dialog_source`` helpers are reused.
"""
from __future__ import annotations

import re

import locale_bundle
from css_rules import declaration, find_rules_with_selector, rules_for_sheet

from _support.claw_static import sheet
from _support.settings_dialog_source import index_elements

_SOURCES = {
    "app": "app.js",
    "dialog": "chat-login-dialog-module.js",
    "auth": "chat-auth-module.js",
    "nav": "chat-nav-module.js",
    "profile_menu": "chat-profile-menu-module.js",
    "capability": "product-capabilities.js",
}


def text(name: str) -> str:
    return sheet(_SOURCES[name])


def lines(name: str) -> list[str]:
    """Whitespace-normalized source lines for code-shape checks."""
    return [re.sub(r"\s+", " ", line).strip() for line in text(name).splitlines()]


def has(name: str, fragment: str) -> bool:
    return any(fragment in line for line in lines(name))


def lacks(name: str, fragment: str) -> bool:
    return not has(name, fragment)


def has_any(names, fragment: str) -> bool:
    return any(has(name, fragment) for name in names)


def section(name: str, start: str, end: str) -> str:
    """The source span between two markers (used for scoped absence checks)."""
    source = text(name)
    return source.split(start, 1)[1].split(end, 1)[0]


def section_lacks(name: str, start: str, end: str, fragment: str) -> bool:
    return fragment not in section(name, start, end)


def css_rules():
    return rules_for_sheet("sidebar-utility.css")


def has_selector(selector: str) -> bool:
    return bool(find_rules_with_selector(css_rules(), selector))


def css_value(selector: str, prop: str):
    found = find_rules_with_selector(css_rules(), selector)
    return declaration(found[0], prop) if found else None


def locale_map(lang: str) -> dict[str, str]:
    return dict(locale_bundle.keys(lang))


def index_ids() -> list[str]:
    return sorted({el.attrs["id"] for el in index_elements() if el.attrs.get("id")})
