"""Source accessors for chat-news and disclosure contracts (#8060).

Raw reads live here. Both tests keep every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path

import locale_bundle

_TESTS = Path(__file__).resolve().parents[1]
_STATIC = _TESTS.parent / "static"


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def news_js() -> str:
    return (_STATIC / "chat-news-module.js").read_text(encoding="utf-8")


def news_css() -> str:
    return (_STATIC / "chat-news.css").read_text(encoding="utf-8")


def tokens_css() -> str:
    return (_STATIC / "padiem-tokens.css").read_text(encoding="utf-8")


def app_js() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")


def locale_source() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")


def news_harness() -> str:
    return (_TESTS / "chat_news_harness.js").read_text(encoding="utf-8")


def conversation_module_js() -> str:
    return (_STATIC / "chat-conversation-module.js").read_text(encoding="utf-8")


def run_history_module_js() -> str:
    return (_STATIC / "chat-run-history-module.js").read_text(encoding="utf-8")


def memory_module_js() -> str:
    return (_STATIC / "chat-memory-module.js").read_text(encoding="utf-8")


def six_panel_css() -> str:
    return (_STATIC / "shared-six-panel-frame.css").read_text(encoding="utf-8")
