"""Static source accessors for the Claw run-event projection contract (#8060).

Raw reads live here. The test keeps its source-absence and markup checks; it
never reads a shipped file itself.
"""
from __future__ import annotations

from _support import claw_static


def projection() -> str:
    return claw_static.sheet("claw-run-event-projection.js")


def app_source() -> str:
    return claw_static.sheet("app.js")


def index_html() -> str:
    return claw_static.sheet("index.html")


def streaming_module() -> str:
    return claw_static.sheet("chat-streaming-module.js")
