"""Source accessors for the R5 A5a/A5b Claw module contracts (#8060).

Raw static reads live here. The two contract tests keep every assertion and
receive the shipped text through these accessors; neither test opens a shipped
file itself. The static directory is also exposed for the Node VM harness.
"""
from __future__ import annotations

from pathlib import Path

from _support import claw_static

_STATIC = Path(__file__).resolve().parents[2] / "static"


def app_js() -> str:
    return claw_static.sheet("app.js")


def index_html() -> str:
    return claw_static.sheet("index.html")


def run_module_js() -> str:
    return claw_static.sheet("chat-claw-run-module.js")


def form_module_js() -> str:
    return claw_static.sheet("chat-claw-form-module.js")


def static_dir() -> str:
    return str(_STATIC)
