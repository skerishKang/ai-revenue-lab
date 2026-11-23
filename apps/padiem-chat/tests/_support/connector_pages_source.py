"""Static source accessors for the connector pages contract (#8060).

Raw reads live here. The test keeps its markup and CSS ownership checks; it
never reads a shipped file itself.
"""
from __future__ import annotations

from _support import claw_static


def html() -> str:
    return claw_static.sheet("index.html")


def pages() -> str:
    return claw_static.sheet("connector-pages.js")


def css() -> str:
    return claw_static.sheet("connector-pages.css")
