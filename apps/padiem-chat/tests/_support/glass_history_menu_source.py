"""Source accessor for the glass history-menu contract (#8060).

The raw read lives here. The test keeps its CSS and browser checks; it never
reads a shipped file itself.
"""
from __future__ import annotations

from pathlib import Path

from _support import claw_static

_STATIC = Path(__file__).resolve().parents[2] / "static"


def shared_frame_css() -> str:
    return claw_static.sheet("shared-six-panel-frame.css")


def static_dir() -> str:
    return str(_STATIC)
