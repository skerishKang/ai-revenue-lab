"""Static source accessors for the login first-paint contract (#8060).

Raw reads live here. The test keeps its markup and CSS ownership checks; it
never reads a shipped file itself.
"""
from __future__ import annotations

from pathlib import Path

from _support import claw_static

_STATIC = Path(__file__).resolve().parents[2] / "static"


def static_path(name: str) -> str:
    return str(_STATIC / name)


def index_html() -> str:
    return claw_static.sheet("index.html")


def auth_session() -> str:
    return claw_static.sheet("auth-session.js")


def capabilities() -> str:
    return claw_static.sheet("product-capabilities.js")


def sidebar_css() -> str:
    return claw_static.sheet("sidebar-utility.css")
