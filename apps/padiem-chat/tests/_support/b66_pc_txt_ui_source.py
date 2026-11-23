"""Static sheet accessor for the B66 PC text UI contract (#8060).

Raw reads live here. The test keeps its route and source-absence checks; it
never reads a shipped file itself.
"""
from __future__ import annotations

from _support import claw_static


def sheet(name: str) -> str:
    return claw_static.sheet(name)
