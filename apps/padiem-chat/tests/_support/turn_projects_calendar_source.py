"""Shipped-source accessors for turn/projects/calendar contracts (#8060).

Raw reads live here. The tests keep every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path

import locale_bundle

_TESTS = Path(__file__).resolve().parents[1]
_STATIC = _TESTS.parent / "static"


def read(name: str) -> str:
    return (_STATIC / name).read_text(encoding="utf-8")


def locale_source() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")


def app_js() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")


def foundation_css() -> str:
    return (_STATIC / "padiem-foundation.css").read_text(encoding="utf-8")


def strict_deps_js() -> str:
    return (_TESTS / "_r5_strict_deps.js").read_text(encoding="utf-8")


def calendar_module_js() -> str:
    return (_STATIC / "chat-calendar-module.js").read_text(encoding="utf-8")


def chat_app_context_js() -> str:
    return (_STATIC / "chat-app-context.js").read_text(encoding="utf-8")


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")
