"""Shipped thought-stream sheets for the #261105 contracts (#8060).

Keeps the raw ``read_text`` calls out of the contract tests: the tests receive
the shipped sources and the locale sheet text, with the file paths here.
"""
from __future__ import annotations

import locale_bundle

from pathlib import Path

_CHAT = Path(__file__).resolve().parents[2]
_STATIC = _CHAT / "static"
_APP = _CHAT / "app"


def streaming_module_source() -> str:
    return (_STATIC / "chat-streaming-module.js").read_text(encoding="utf-8")


def transport_source() -> str:
    return (_STATIC / "chat-transport.js").read_text(encoding="utf-8")


def locale_source() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")


def capability_presentation_css() -> str:
    return (_STATIC / "capability-presentation.css").read_text(encoding="utf-8")


def conversation_export_source() -> str:
    return (_STATIC / "conversation-export.js").read_text(encoding="utf-8")


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def thought_panel_source() -> str:
    return (_STATIC / "thought-panel.js").read_text(encoding="utf-8")


def message_lifecycle_source() -> str:
    return (_STATIC / "message-lifecycle.js").read_text(encoding="utf-8")


def chat_routes_source() -> str:
    return (_APP / "chat_routes.py").read_text(encoding="utf-8")


def orchestration_routes_source() -> str:
    return (_APP / "orchestration_routes.py").read_text(encoding="utf-8")
