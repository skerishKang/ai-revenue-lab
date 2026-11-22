"""Shipped settings/sidebar-module sheets for the R5 contracts (#8060).

Keeps the raw ``read_text`` calls out of the contract tests: the tests receive
the shipped app, module and page sheets, with the sheet paths here.
"""
from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"


def static_dir() -> Path:
    return _STATIC


def app_js() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")


def settings_js() -> str:
    return (_STATIC / "chat-settings-module.js").read_text(encoding="utf-8")


def sidebar_js() -> str:
    return (_STATIC / "chat-sidebar-module.js").read_text(encoding="utf-8")


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def module_source(filename: str) -> str:
    return (_STATIC / filename).read_text(encoding="utf-8")
