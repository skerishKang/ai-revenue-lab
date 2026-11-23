"""Source accessors for the chat static card/layout contracts (#8060).

Raw static reads live here. The error-card polish and the first-turn layout
tests keep their assertions and receive shipped text through these accessors.
"""
from __future__ import annotations

from pathlib import Path

from _support import claw_static

_STATIC = Path(__file__).resolve().parents[2] / "static"


def sheet(name: str) -> str:
    return claw_static.sheet(name)


def static_path(name: str) -> str:
    return str(_STATIC / name)
