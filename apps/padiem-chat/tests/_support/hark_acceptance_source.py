"""Source accessor for the HARK acceptance contract (#8060).

The raw read lives here. The test keeps its shipped-fact assertions; it never
reads a source file itself.
"""
from __future__ import annotations

from _support import claw_static


def acceptance_source() -> str:
    return claw_static.server_source("hark_3936_acceptance")
