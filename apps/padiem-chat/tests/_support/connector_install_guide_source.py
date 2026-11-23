"""Source accessors for the connector install-guide contract (#8060).

Raw reads live here. The test keeps its touch-target and code-grounded copy
checks; it never reads a shipped file itself.
"""
from __future__ import annotations

from pathlib import Path

from _support import claw_static

_STATIC = Path(__file__).resolve().parents[2] / "static"


def help_html() -> str:
    return claw_static.sheet("help.html")


def install_html() -> str:
    return claw_static.sheet("install.html")


def help_css() -> str:
    return claw_static.sheet("help.css")


def static_dir() -> str:
    return str(_STATIC)


def repo_text(relative: str) -> str:
    return claw_static.repo_source(relative)
