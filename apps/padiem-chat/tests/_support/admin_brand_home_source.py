"""Shipped-source accessors for admin/brand/home contracts (#8060).

Raw reads live here. The tests keep every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path

import locale_bundle

_CHAT = Path(__file__).resolve().parents[2]
_STATIC = _CHAT / "static"


def read(path) -> str:
    return Path(path).read_text(encoding="utf-8")


def capabilities_js() -> str:
    return (_STATIC / "product-capabilities.js").read_text(encoding="utf-8")


def app_js() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")


def settings_js() -> str:
    return (_STATIC / "chat-settings-module.js").read_text(encoding="utf-8")


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def install_html() -> str:
    return (_STATIC / "install.html").read_text(encoding="utf-8")


def locale_source() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")


def b66_quote_routes() -> str:
    return (_CHAT / "app" / "b66_quote_routes.py").read_text(encoding="utf-8")


def connector_owner_setup_page() -> str:
    return (_CHAT / "app" / "connector_owner_setup_page.py").read_text(encoding="utf-8")


def six_panel_css() -> str:
    return (_STATIC / "shared-six-panel-frame.css").read_text(encoding="utf-8")


def theme_js() -> str:
    return (_STATIC / "theme.js").read_text(encoding="utf-8")
