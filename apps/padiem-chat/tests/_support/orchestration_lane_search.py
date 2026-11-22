"""Shipped lane-search sheets for the #4469 contracts (#8060).

Keeps the raw ``read_text`` calls out of the contract tests: the tests receive
the shipped sources, with the sheet paths here.
"""
from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"


def search_sources_js() -> str:
    return (_STATIC / "search-sources.js").read_text(encoding="utf-8")


def app_source() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")


def conversation_module_source() -> str:
    return (_STATIC / "chat-conversation-module.js").read_text(encoding="utf-8")


def streaming_module_source() -> str:
    return (_STATIC / "chat-streaming-module.js").read_text(encoding="utf-8")


def transport_source() -> str:
    return (_STATIC / "chat-transport.js").read_text(encoding="utf-8")
