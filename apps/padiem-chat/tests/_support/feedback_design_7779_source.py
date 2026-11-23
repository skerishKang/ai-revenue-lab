"""Source accessors for the feedback design contract (#8060).

Raw reads live here. The test keeps every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"


def feedback_module_js() -> str:
    return (_STATIC / "chat-feedback-module.js").read_text(encoding="utf-8")


def feedback_css() -> str:
    return (_STATIC / "chat-feedback.css").read_text(encoding="utf-8")


def tokens_css() -> str:
    return (_STATIC / "padiem-tokens.css").read_text(encoding="utf-8")


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")
