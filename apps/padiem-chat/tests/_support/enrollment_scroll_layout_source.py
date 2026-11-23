"""Shipped-source accessors for enrollment/scroll/layout contracts (#8060).

Raw reads live here. The tests keep every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[4]
_STATIC = _REPO / "apps" / "padiem-chat" / "static"


def read(path) -> str:
    return Path(path).read_text(encoding="utf-8")


def read_repo(relative: str) -> str:
    return (_REPO / relative).read_text(encoding="utf-8")


def consent_js() -> str:
    return (_STATIC / "claw-pc-enrollment-consent.js").read_text(encoding="utf-8")


def chat_ui_polish_css() -> str:
    return (_STATIC / "padiem-chat-ui-polish.css").read_text(encoding="utf8")


def claw_focus_layout_css() -> str:
    return (_STATIC / "claw-focus-layout.css").read_text(encoding="utf8")


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf8")


def app_js() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf8")
