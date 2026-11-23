"""Source accessors for the Mesh-only presence contract (#8060).

Raw reads live here. The test keeps its store behavior and directory projection
contracts; it never reads a shipped file itself.
"""
from __future__ import annotations

from pathlib import Path

from _support import claw_static

_STATIC = Path(__file__).resolve().parents[2] / "static"


def migration(name: str) -> str:
    return claw_static.migration_source(name)


def static_path(name: str) -> str:
    return str(_STATIC / name)
