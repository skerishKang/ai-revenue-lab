"""Static source accessors for the shared capability presentation contract (#8060).

Raw reads live here. The test keeps its parsed source and CSS checks; it never
reads a shipped file itself.
"""
from __future__ import annotations

from _support import claw_static


def lifecycle() -> str:
    return claw_static.sheet("message-lifecycle.js")


def capability_css() -> str:
    return claw_static.sheet("capability-presentation.css")
