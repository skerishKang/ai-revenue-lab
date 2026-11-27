"""Source accessors for Chat/Claw shipped-source contracts (#8060).

Raw reads live here. Both tests keep every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path

import locale_bundle

_CHAT = Path(__file__).resolve().parents[2]
_STATIC = _CHAT / "static"


def attachment_capabilities_js() -> str:
    return (_STATIC / "attachment-capabilities.js").read_text(encoding="utf-8")


def document_binary_js() -> str:
    return (_STATIC / "document-binary.js").read_text(encoding="utf-8")


def app_js() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")


def locale_source() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def stream_js() -> str:
    return (_STATIC / "chat-streaming-module.js").read_text(encoding="utf-8")


def settings_js() -> str:
    return (_STATIC / "chat-settings-module.js").read_text(encoding="utf-8")


def claw_general_routes() -> str:
    from _support.claw_general_modules import sources

    return sources()
