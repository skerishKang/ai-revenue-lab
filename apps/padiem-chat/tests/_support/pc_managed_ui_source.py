"""Source accessors for the managed-PC admin UI contract (#8060).

Raw reads live here. The test keeps every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path

import locale_bundle

_STATIC = Path(__file__).resolve().parents[2] / "static"


def admin_html() -> str:
    return (_STATIC / "admin.html").read_text(encoding="utf-8")


def admin_js() -> str:
    return (_STATIC / "admin.js").read_text(encoding="utf-8")


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def mcp_settings_js() -> str:
    return (_STATIC / "mcp-gateway-settings.js").read_text(encoding="utf-8")


def locale_source() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")


def ui_polish_css() -> str:
    return (_STATIC / "padiem-chat-ui-polish.css").read_text(encoding="utf-8")
