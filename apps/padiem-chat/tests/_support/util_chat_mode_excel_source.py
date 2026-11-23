"""Static source accessors for the util chat-mode/Excel contract (#8060).

Raw reads live here. The test keeps its wiring and Node behavior checks; it
never reads a shipped file itself.
"""
from __future__ import annotations

from pathlib import Path

from _support import claw_static

_STATIC = Path(__file__).resolve().parents[2] / "static"


def app_js() -> str:
    return claw_static.sheet("app.js")


def manifest_js() -> str:
    return claw_static.sheet("util-manifest.js")


def chat_mode_js() -> str:
    return claw_static.sheet("util-chat-mode.js")


def excel_js() -> str:
    return claw_static.sheet("util-excel.js")


def static_path(name: str) -> str:
    return str(_STATIC / name)
