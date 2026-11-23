"""Source accessors for locale, usage-log and composer contracts (#8060).

Raw reads live here. The contract tests keep their assertions and receive
shipped text or stable paths through these accessors.
"""
from __future__ import annotations

from pathlib import Path

from _support import claw_static

_STATIC = Path(__file__).resolve().parents[2] / "static"
_REPO = Path(__file__).resolve().parents[4]


def sheet(name: str) -> str:
    return claw_static.sheet(name)


def locale_js() -> str:
    return claw_static.locale_source()


def source(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")


def repo_source(relative: str) -> str:
    return (_REPO / relative).read_text(encoding="utf-8")


def static_dir() -> str:
    return str(_STATIC)
