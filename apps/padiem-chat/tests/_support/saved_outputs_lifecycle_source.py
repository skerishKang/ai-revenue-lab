"""Static source accessor for the saved-outputs lifecycle contract (#8060).

The raw read lives here. The test keeps its source assertions; it never reads a
shipped file itself.
"""
from __future__ import annotations

from _support import claw_static


def outputs_js() -> str:
    return claw_static.sheet("outputs.js")
