"""Static sheet accessors for the input-cell/frame layout contract (#8060).

Raw reads live here. The test keeps its measured declaration values; it never
reads a shipped sheet itself.
"""
from __future__ import annotations

from _support import claw_static


def frame() -> str:
    return claw_static.sheet("shared-six-panel-frame.css")


def glass() -> str:
    return claw_static.sheet("padiem-glass.css")


def claw() -> str:
    return claw_static.sheet("claw-focus-layout.css")


def workspace() -> str:
    return claw_static.sheet("claw-workspace.css")
