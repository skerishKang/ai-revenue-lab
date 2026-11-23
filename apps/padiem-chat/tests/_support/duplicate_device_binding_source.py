"""Static sheet accessor for the duplicate device binding contract (#8060).

The raw read lives here. The test keeps its route and page checks; it never reads
a shipped file itself.
"""
from __future__ import annotations

from _support import claw_static


def sheet(name: str) -> str:
    return claw_static.sheet(name)
