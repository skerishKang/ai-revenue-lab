"""Static sheet accessors for the shared gutter layout contract (#8060).

Raw reads live here. The test keeps its declaration and absence contracts; it
never reads a shipped sheet itself.
"""
from __future__ import annotations

from _support import claw_static


def alignment_css() -> str:
    return claw_static.sheet("padiem-glass-gutter-alignment.css")


def chat_css() -> str:
    return claw_static.sheet("padiem-cinematic-chat.css")


def index_html() -> str:
    return claw_static.sheet("index.html")
