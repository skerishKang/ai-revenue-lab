"""Source accessors for CSS and source-display contracts (#8060).

Raw reads live here. The contract tests keep their assertions and receive
shipped text or stable paths through these accessors.
"""
from __future__ import annotations

from pathlib import Path

from _support import claw_static

_STATIC = Path(__file__).resolve().parents[2] / "static"


def sheet(name: str) -> str:
    return claw_static.sheet(name)


def static_path(name: str) -> Path:
    return _STATIC / name


def static_root() -> Path:
    return _STATIC
