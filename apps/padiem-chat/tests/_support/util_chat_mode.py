"""Shipped Util chat-mode sheets for the #7461 contracts (#8060).

Keeps the raw ``read_text`` calls out of the contract tests: the tests receive
the shipped page, module and style sheets, with the sheet paths here.
"""
from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"


def static_dir() -> Path:
    return _STATIC


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def chat_mode_js() -> str:
    return (_STATIC / "util-chat-mode.js").read_text(encoding="utf-8")


def chat_mode_css() -> str:
    return (_STATIC / "util-chat-mode.css").read_text(encoding="utf-8")


def tools_js() -> str:
    return (_STATIC / "util-tools.js").read_text(encoding="utf-8")


def app_js() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")
