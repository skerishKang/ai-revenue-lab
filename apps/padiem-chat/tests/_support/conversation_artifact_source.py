"""Parsed/tokenized views for the #3933 conversation artifact contracts (#8060).

Raw file reads live here. Tests receive tokenized sources and parsed HTML facts.
The shared ``claw_static`` and ``locale_bundle`` helpers are reused.
"""
from __future__ import annotations

import re

import locale_bundle

from _support.claw_static import sheet

_SHEETS = {
    "context": "claw-conversation-artifact-context.js",
    "app": "app.js",
    "nav": "chat-nav-module.js",
    "panel": "claw-web-xlsx-sources.js",
    "index": "index.html",
}

_STRING_RX = re.compile(r'"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\'')
_IDENTIFIER_RX = re.compile(r"[A-Za-z_$][\w$]*")


def text(key: str) -> str:
    return sheet(_SHEETS[key])


def tokens(key: str) -> set[str]:
    source = text(key)
    identifiers = set(_IDENTIFIER_RX.findall(source))
    strings = {double or single for double, single in _STRING_RX.findall(source)}
    return identifiers | strings


def has(key: str, fragment: str) -> bool:
    return any(
        fragment in re.sub(r"\s+", " ", line).strip()
        for line in text(key).splitlines()
    )


def lacks(key: str, fragment: str) -> bool:
    return not has(key, fragment)


def script_src_count(value: str) -> int:
    return len(re.findall(r'src="' + re.escape(value) + r'"', text("index")))


def script_src_before(first: str, second: str) -> bool:
    source = text("index")
    return source.index(f'src="{first}"') < source.index(f'src="{second}"')


def locale_has_key(key: str) -> bool:
    return any(key in locale_bundle.keys(lang) for lang in ("ko", "en"))
