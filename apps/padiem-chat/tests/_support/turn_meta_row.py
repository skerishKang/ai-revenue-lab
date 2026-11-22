"""Shipped turn-meta-row sheets for the #4485 contracts (#8060).

Keeps the raw ``read_text`` calls out of the contract tests: the tests receive
the shipped modules and style sheets, with the sheet paths here.
"""
from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"


def static_dir() -> Path:
    """The directory the offline fixture server serves (the shipped sheets)."""
    return _STATIC


def app_js() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")


def lifecycle_js() -> str:
    return (_STATIC / "message-lifecycle.js").read_text(encoding="utf-8")


def pc_run_js() -> str:
    return (_STATIC / "chat-pc-run-module.js").read_text(encoding="utf-8")


def streaming_js() -> str:
    return (_STATIC / "chat-streaming-module.js").read_text(encoding="utf-8")


def glass_css() -> str:
    return (_STATIC / "padiem-glass-portrait.css").read_text(encoding="utf-8")


def answer_css() -> str:
    return (_STATIC / "answer-actions.css").read_text(encoding="utf-8")
