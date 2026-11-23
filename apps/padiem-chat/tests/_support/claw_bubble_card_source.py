"""Source accessors for the Claw bubble contrast and run-card tests (#8060).

Raw reads live here. Both contract tests keep their assertions and receive
shipped text through these accessors.
"""
from __future__ import annotations

from pathlib import Path

from _support import claw_static

_STATIC = Path(__file__).resolve().parents[2] / "static"


def css_text(name: str) -> str:
    return claw_static.sheet(name)


def app_js() -> str:
    return claw_static.sheet("app.js")


def static_path(name: str) -> str:
    return str(_STATIC / name)
