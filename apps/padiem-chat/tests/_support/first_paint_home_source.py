"""Source accessors for the first-paint and home-link tests (#8060).

Raw reads live here. Both contract tests keep their assertions and receive
shipped text through these accessors; byte-level checks get the stable path.
"""
from __future__ import annotations

from pathlib import Path

from _support import claw_static

_STATIC = Path(__file__).resolve().parents[2] / "static"


def index_html() -> str:
    return claw_static.sheet("index.html")


def glass_css() -> str:
    return claw_static.sheet("padiem-glass.css")


def glass_portrait_css() -> str:
    return claw_static.sheet("padiem-glass-portrait.css")


def theme_init_js() -> str:
    return claw_static.sheet("theme-init.js")


def static_path(name: str) -> Path:
    return _STATIC / name
