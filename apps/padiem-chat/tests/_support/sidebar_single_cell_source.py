"""Static source accessors for the sidebar single-cell contract (#8060).

Raw reads live here. The test keeps its parsed markup and CSS ownership checks;
it never reads a shipped file itself.
"""
from __future__ import annotations

from _support import claw_static


def html() -> str:
    return claw_static.sheet("index.html")


def css() -> str:
    return claw_static.sheet("sidebar-unified.css")


def app() -> str:
    return (claw_static.sheet("app.js") + "\n"
            + claw_static.sheet("chat-history-module.js"))


def search() -> str:
    return claw_static.sheet("conversation-search.js")
