"""Static sheet accessor for the auth panel token contract (#8060).

The raw read lives here. The test keeps its parsed declaration checks; it never
reads a shipped sheet itself.
"""
from __future__ import annotations

from _support import claw_static


def sheet(name: str) -> str:
    return claw_static.sheet(name)
