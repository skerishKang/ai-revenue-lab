"""Shipped-source accessors for shared conversation contracts (#8060).

Raw reads live here. The tests keep every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[4]
_STATIC = _REPO / "apps/padiem-chat/static"
_B66 = _REPO / "reference/business-66-padiem-quote-v1"


def read(path) -> str:
    return Path(path).read_text(encoding="utf-8")


def read_static(name: str) -> str:
    return (_STATIC / name).read_text(encoding="utf-8")


def scroll_source_text() -> str:
    return (_REPO / "packages/padiem-conversation-ui/scroll-follow.js").read_text(encoding="utf-8")


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def app_js() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")


def b66_index_html() -> str:
    return (_B66 / "index.html").read_text(encoding="utf-8")


def b66_easy_mode_js() -> str:
    return (_B66 / "easy-mode.js").read_text(encoding="utf-8")
