"""Source accessors for the Claw preview DOM-sink contract (#8060).

Raw reads live here. The test keeps every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def app_js() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")


def form_js() -> str:
    return (_STATIC / "chat-claw-form-module.js").read_text(encoding="utf-8")
