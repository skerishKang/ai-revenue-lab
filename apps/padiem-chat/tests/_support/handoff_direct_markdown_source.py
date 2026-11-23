"""Shipped-source accessors for handoff/direct-UI/markdown contracts (#8060).

Raw reads live here. The tests keep every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path

_CHAT = Path(__file__).resolve().parents[2]
_STATIC = _CHAT / "static"


def read(path, encoding: str = "utf-8") -> str:
    return Path(path).read_text(encoding=encoding)


def home_choices_js() -> str:
    return (_STATIC / "claw-home-choices.js").read_text(encoding="utf-8")


def app_js() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")


def conversation_js() -> str:
    return (_STATIC / "chat-conversation-module.js").read_text(encoding="utf-8")


def streaming_js() -> str:
    return (_STATIC / "chat-streaming-module.js").read_text(encoding="utf-8")


def history_js() -> str:
    return (_STATIC / "chat-history-module.js").read_text(encoding="utf-8")


def run_history_js() -> str:
    return (_STATIC / "chat-run-history-module.js").read_text(encoding="utf-8")


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def six_panel_css() -> str:
    return (_STATIC / "shared-six-panel-frame.css").read_text(encoding="utf-8")


def chat_routes() -> str:
    return (_CHAT / "app" / "chat_routes.py").read_text(encoding="utf-8")
