"""Parsed views for the util design contracts (#8060).

Raw file reads live here. Tests receive parsed HTML ids/tags, CSS rules and JS
tokens. Existing ``claw_static``, ``css_rules`` and ``settings_dialog_source``
helpers are reused for the underlying reads and parsing.
"""
from __future__ import annotations

import re

from css_rules import parse_rules

from _support.claw_static import sheet
from _support.settings_dialog_source import index_elements

_STRING_RX = re.compile(r'"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\'')
_IDENTIFIER_RX = re.compile(r"[A-Za-z_$][\w$]*")


# ----------------------------------------------------------- index.html

def index_text() -> str:
    return sheet("index.html")


def index_ids() -> list[str]:
    return [el.attrs["id"] for el in index_elements() if el.attrs.get("id")]


def index_has_class(name: str) -> bool:
    return any(
        name in (el.attrs.get("class") or "").split() for el in index_elements()
    )


def index_script_attrs() -> list[dict[str, str | None]]:
    return [el.attrs for el in index_elements() if el.tag == "script"]


# --------------------------------------------------------------- CSS

def util_app_rules():
    return parse_rules(sheet("util-app.css"))


def util_tools_rules():
    return parse_rules(sheet("util-tools.css"))


# --------------------------------------------------------------- app.js

def chat_app_tokens() -> set[str]:
    """Identifiers and string literals in the shipped app.js."""
    source = sheet("app.js")
    identifiers = set(_IDENTIFIER_RX.findall(source))
    strings = {double or single for double, single in _STRING_RX.findall(source)}
    return identifiers | strings


def chat_app_line_count() -> int:
    return len(sheet("app.js").splitlines())
