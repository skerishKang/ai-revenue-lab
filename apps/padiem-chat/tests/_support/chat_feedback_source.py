"""Static source accessors for the chat feedback UI contract (#8060).

Raw reads live here. The test keeps its behavior, markup and copy checks; it
never reads a shipped file itself.
"""
from __future__ import annotations

from pathlib import Path

import locale_bundle
from _support import claw_static

_STATIC = Path(__file__).resolve().parents[2] / "static"


def static_dir() -> str:
    return str(_STATIC)


def index_html() -> str:
    return claw_static.sheet("index.html")


def feedback_js() -> str:
    return claw_static.sheet("chat-feedback-module.js")


def feedback_css() -> str:
    return claw_static.sheet("chat-feedback.css")


def app_js() -> str:
    return claw_static.sheet("app.js")


def locale_source() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")
