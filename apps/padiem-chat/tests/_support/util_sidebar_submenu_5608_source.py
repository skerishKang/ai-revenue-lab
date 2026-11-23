"""Source accessors for the Util sidebar submenu contract (#8060).

Raw shipped-source reads live here. The test keeps every assertion unchanged and
never reads a shipped file itself.
"""
from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def util_manifest_js() -> str:
    return (_STATIC / "util-manifest.js").read_text(encoding="utf-8")


def util_menu_js() -> str:
    return (_STATIC / "util-menu.js").read_text(encoding="utf-8")


def util_menu_css() -> str:
    return (_STATIC / "util-menu.css").read_text(encoding="utf-8")


def util_app_css() -> str:
    return (_STATIC / "util-app.css").read_text(encoding="utf-8")
