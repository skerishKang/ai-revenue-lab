"""Shipped frontend-ownership sheets for the B62 contracts (#8060).

Keeps the raw ``read_text`` calls out of the contract tests: the tests receive
the shipped browser sources and the page sheet, with the sheet paths here.
"""
from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"


def app_js() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")


def streaming_js() -> str:
    return (_STATIC / "chat-streaming-module.js").read_text(encoding="utf-8")


def transport_js() -> str:
    return (_STATIC / "chat-transport.js").read_text(encoding="utf-8")


def lifecycle_js() -> str:
    return (_STATIC / "message-lifecycle.js").read_text(encoding="utf-8")


def rich_response_js() -> str:
    return (_STATIC / "rich-response.js").read_text(encoding="utf-8")


def conversation_state_js() -> str:
    return (_STATIC / "conversation-state.js").read_text(encoding="utf-8")


def document_binary_js() -> str:
    return (_STATIC / "document-binary.js").read_text(encoding="utf-8")


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")
