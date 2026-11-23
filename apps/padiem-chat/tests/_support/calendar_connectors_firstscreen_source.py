"""Shipped-source accessors for calendar/connectors/first-screen contracts (#8060).

Raw reads live here. The tests keep every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path

import locale_bundle

_STATIC = Path(__file__).resolve().parents[2] / "static"


def read(path) -> str:
    return Path(path).read_text(encoding="utf-8")


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def app_js() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")


def connectors_module_js() -> str:
    return (_STATIC / "chat-connectors-module.js").read_text(encoding="utf-8")


def locale_source() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")


def util_app_css() -> str:
    return (_STATIC / "util-app.css").read_text(encoding="utf-8")


def util_app_js() -> str:
    return (_STATIC / "util-app.js").read_text(encoding="utf-8")
