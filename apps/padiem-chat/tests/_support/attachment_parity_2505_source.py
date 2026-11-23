"""Source accessors for the Chat/Claw attachment parity contract (#8060).

Raw shipped-source reads live here. The test keeps every assertion unchanged and
never reads a shipped file itself.
"""
from __future__ import annotations

from pathlib import Path

import locale_bundle

_ROOT = Path(__file__).resolve().parents[2]


def app_js() -> str:
    return (_ROOT / "static" / "app.js").read_text(encoding="utf-8")


def stream_js() -> str:
    return (_ROOT / "static" / "chat-streaming-module.js").read_text(encoding="utf-8")


def locale_js() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")


def transport_js() -> str:
    return (_ROOT / "static" / "chat-transport.js").read_text(encoding="utf-8")


def chat_routes() -> str:
    return (_ROOT / "app" / "chat_routes.py").read_text(encoding="utf-8")


def claw_general_routes() -> str:
    return (_ROOT / "app" / "claw_general_routes.py").read_text(encoding="utf-8")


def conversation_js() -> str:
    return (_ROOT / "static" / "chat-conversation-module.js").read_text(encoding="utf-8")
