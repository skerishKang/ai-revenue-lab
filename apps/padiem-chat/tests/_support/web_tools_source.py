"""Static sheet accessor for the web-tools removal contract (#8060).

The raw read lives here. The test keeps its absence assertions; it never reads a
shipped file itself.
"""
from __future__ import annotations

from _support import claw_static


def index_html() -> str:
    return claw_static.sheet("index.html")
