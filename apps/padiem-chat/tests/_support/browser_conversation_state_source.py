"""Static source accessors for the conversation state browser contract (#8060).

Raw reads live here. The test keeps its load-order, ownership and executed state
contracts; it never reads a shipped file itself.
"""
from __future__ import annotations

from pathlib import Path

from _support import claw_static

_STATIC = Path(__file__).resolve().parents[2] / "static"


def index_html() -> str:
    return claw_static.sheet("index.html")


def state_source() -> str:
    return claw_static.sheet("conversation-state.js")


def app_source() -> str:
    return claw_static.sheet("app.js")


def conversation_module() -> str:
    return claw_static.sheet("chat-conversation-module.js")


def streaming_module() -> str:
    return claw_static.sheet("chat-streaming-module.js")


def state_path() -> str:
    return str(_STATIC / "conversation-state.js")
