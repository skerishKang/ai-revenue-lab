"""Shipped-source accessors for consent/util/guidance contracts (#8060).

Raw reads live here. The tests keep every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path

import locale_bundle

_STATIC = Path(__file__).resolve().parents[2] / "static"


def read(path) -> str:
    return Path(path).read_text(encoding="utf-8")


def mcp_oauth_consent_js() -> str:
    return (_STATIC / "mcp-oauth-consent.js").read_text(encoding="utf-8")


def locale_source() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def util_menu_css() -> str:
    return (_STATIC / "util-menu.css").read_text(encoding="utf-8")


def util_menu_js() -> str:
    return (_STATIC / "util-menu.js").read_text(encoding="utf-8")


def app_js() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")


def nav_module_js() -> str:
    return (_STATIC / "chat-nav-module.js").read_text(encoding="utf-8")


def util_manifest_js() -> str:
    return (_STATIC / "util-manifest.js").read_text(encoding="utf-8")


def calendar_module_js() -> str:
    return (_STATIC / "chat-calendar-module.js").read_text(encoding="utf-8")


def connectors_module_js() -> str:
    return (_STATIC / "chat-connectors-module.js").read_text(encoding="utf-8")
