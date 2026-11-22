"""Shipped sidebar-profile sheets for the #4416 contracts (#8060).

Keeps the raw ``read_text`` calls out of the contract tests: the tests receive
the shipped sources and the locale sheet text, with the sheet paths here.
"""
from __future__ import annotations

import locale_bundle

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def app_source() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")


def auth_module_source() -> str:
    return (_STATIC / "chat-auth-module.js").read_text(encoding="utf-8")


def sidebar_module_source() -> str:
    return (_STATIC / "chat-sidebar-module.js").read_text(encoding="utf-8")


def sidebar_utility_css() -> str:
    return (_STATIC / "sidebar-utility.css").read_text(encoding="utf-8")


def locale_source() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")
