"""Source accessors for plain-error copy and quick-launcher tests (#8060).

Raw reads live here. Both contract tests keep their assertions and receive
shipped text or stable paths through these accessors.
"""
from __future__ import annotations

from pathlib import Path

from _support import claw_static

_STATIC = Path(__file__).resolve().parents[2] / "static"


def sheet(name: str) -> str:
    return claw_static.sheet(name)


def locale_js() -> str:
    return claw_static.locale_source()


def static_path(name: str) -> Path:
    return _STATIC / name


def static_dir() -> Path:
    return _STATIC
