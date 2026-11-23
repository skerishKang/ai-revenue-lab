"""Static sheet accessors for the message-lifecycle browser contract (#8060).

Raw reads live here. The test keeps its markup and source checks; it never reads
a shipped file itself.
"""
from __future__ import annotations

from _support import claw_static


def sheet(name: str) -> str:
    return claw_static.sheet(name)
