"""Static sheet accessors for the calendar range-save contract (#8060).

Raw reads live here. The test keeps its parsed CSS and markup checks; it never
reads a shipped file itself.
"""
from __future__ import annotations

from _support import claw_static


def sheet(name: str) -> str:
    return claw_static.sheet(name)
