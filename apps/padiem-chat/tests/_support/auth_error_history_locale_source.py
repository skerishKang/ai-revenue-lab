"""Shipped-source accessors for auth-error/history/locale contracts (#8060).

Raw reads live here. The tests keep every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path

import locale_bundle

_STATIC = Path(__file__).resolve().parents[2] / "static"


def read(name: str) -> str:
    return (_STATIC / name).read_text(encoding="utf-8")


def locale_source() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")


def app_js() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")


def history_module_js() -> str:
    return (_STATIC / "chat-history-module.js").read_text(encoding="utf-8")


def project_module_js() -> str:
    return (_STATIC / "chat-project-module.js").read_text(encoding="utf-8")


def history_css() -> str:
    return (_STATIC / "history.css").read_text(encoding="utf-8")


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def outputs_js() -> str:
    return (_STATIC / "outputs.js").read_text(encoding="utf-8")


def conversation_search_js() -> str:
    return (_STATIC / "conversation-search.js").read_text(encoding="utf-8")
