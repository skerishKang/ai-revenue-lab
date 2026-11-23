"""Source accessors for the shared-scroll wiring and thread layout tests (#8060).

Raw reads live here. Both contract tests keep their assertions and receive
shipped text through these accessors.
"""
from __future__ import annotations

from pathlib import Path

from _support import claw_static

_REPO = Path(__file__).resolve().parents[4]


def repo_source(relative: str) -> str:
    return (_REPO / relative).read_text(encoding="utf-8")


def sheet(name: str) -> str:
    return claw_static.sheet(name)
