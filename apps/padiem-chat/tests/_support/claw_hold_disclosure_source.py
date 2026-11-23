"""Source accessors for the Claw model-hold copy and disclosure guards (#8060).

Raw static reads live here. The two contract tests keep their assertions and
receive the shipped text through these accessors; the static directory is
exposed for the Node VM harness used by the model-hold test.
"""
from __future__ import annotations

from pathlib import Path

from _support import claw_static

_STATIC = Path(__file__).resolve().parents[2] / "static"


def app_js() -> str:
    return claw_static.sheet("app.js")


def session_js() -> str:
    return claw_static.sheet("claw-session.js")


def index_html() -> str:
    return claw_static.sheet("index.html")


def locale_js() -> str:
    return claw_static.locale_source()


def static_dir() -> str:
    return str(_STATIC)
