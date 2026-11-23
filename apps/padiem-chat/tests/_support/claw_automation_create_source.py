"""Static source accessors for the Claw automation create UI contract (#8060).

Raw reads live here. The test keeps its parsed CSS, locale ownership and Node
behavior checks; it never reads a shipped file itself.
"""
from __future__ import annotations

from pathlib import Path

import locale_bundle
from _support import claw_static

_STATIC = Path(__file__).resolve().parents[2] / "static"


def app_source() -> str:
    return claw_static.sheet("app.js")


def index_html() -> str:
    return claw_static.sheet("index.html")


def form_module() -> str:
    return claw_static.sheet("chat-automation-form-module.js")


def automation_module() -> str:
    return claw_static.sheet("chat-automation-module.js")


def local_pc_panel_module() -> str:
    return claw_static.sheet("chat-local-pc-panel-module.js")


def locale_source() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")


def workspace_css() -> str:
    return claw_static.sheet("claw-workspace.css")


def app_js_path() -> str:
    return str(_STATIC / "app.js")


def test_path(name: str) -> str:
    return str(Path(__file__).resolve().parents[1] / name)
