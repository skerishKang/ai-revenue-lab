"""Static source accessors for the Claw connection guide contract (#8060).

Raw reads live here. The test keeps its markup, script and style checks; it
never reads a shipped file itself.
"""
from __future__ import annotations

from _support import claw_static


def index_html() -> str:
    return claw_static.sheet("index.html")


def guide_script() -> str:
    return claw_static.sheet("claw-connection-guide.js")


def guide_style() -> str:
    return claw_static.sheet("claw-connection-guide.css")
