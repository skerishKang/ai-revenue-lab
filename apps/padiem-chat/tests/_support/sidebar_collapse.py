"""Shipped sidebar-collapse sheets for the #4890 one-cell contracts (#8060 54차).

Keeps the raw ``read_text`` calls out of the contract tests: the tests receive
the shipped sources, with the sheet paths here.
"""
from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def sidebar_section_collapse_js() -> str:
    return (_STATIC / "sidebar-section-collapse.js").read_text(encoding="utf-8")


def sidebar_section_polish_css() -> str:
    return (_STATIC / "sidebar-section-polish.css").read_text(encoding="utf-8")


def app_source() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")


def chat_history_module_source() -> str:
    return (_STATIC / "chat-history-module.js").read_text(encoding="utf-8")


def glass_css() -> str:
    return (_STATIC / "padiem-glass.css").read_text(encoding="utf-8")
