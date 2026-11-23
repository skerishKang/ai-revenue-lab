"""Static sheet accessors for the CSS-rule helper contract (#8060).

Raw reads live here. The test keeps its parsed-rule assertions; it never reads a
shipped file itself.
"""
from __future__ import annotations

from _support import claw_static


def sheet(name: str) -> str:
    return claw_static.sheet(name)
