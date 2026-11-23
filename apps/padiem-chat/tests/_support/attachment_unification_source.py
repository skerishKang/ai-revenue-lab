"""Attachment-unification contract raw reads (#8060).

Raw reads live here. Tests assert on parsed tokens and values from the
returned text. The shared ``claw_static`` helper is untouched.
"""
from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"


def app_js() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")


def stream_js() -> str:
    return (_STATIC / "chat-streaming-module.js").read_text(encoding="utf-8")


def binary_js() -> str:
    return (_STATIC / "document-binary.js").read_text(encoding="utf-8")


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")
