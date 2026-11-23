"""Shipped-source accessors for projects/recovery/template contracts (#8060).

Raw reads live here. The tests keep every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"


def read(name: str) -> str:
    return (_STATIC / name).read_text(encoding="utf-8")


def app_js() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")


def stream_js() -> str:
    return (_STATIC / "chat-streaming-module.js").read_text(encoding="utf-8")


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def lifecycle_js() -> str:
    return (_STATIC / "message-lifecycle.js").read_text(encoding="utf-8")


def recovery_js() -> str:
    return (_STATIC / "claw-recovery-truth.js").read_text(encoding="utf-8")


def event_js() -> str:
    return (_STATIC / "claw-run-event-projection.js").read_text(encoding="utf-8")


def quote_runtime_js() -> str:
    return (_STATIC / "b66-quote-runtime.js").read_text(encoding="utf-8")
