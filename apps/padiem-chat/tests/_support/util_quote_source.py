"""Shipped sources for the #7173 quote-draft contracts (#8060).

The raw ``read_text`` calls live here so the contract test does not pin source
spelling; paths and parsed views are the helper's responsibility.
"""
from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"


def index_source() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def quote_js_source() -> str:
    return (_STATIC / "util-quote.js").read_text(encoding="utf-8")


def quote_css_source() -> str:
    return (_STATIC / "util-quote.css").read_text(encoding="utf-8")


def util_app_source() -> str:
    return (_STATIC / "util-app.js").read_text(encoding="utf-8")


def app_source() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")


def markdown_source() -> str:
    return (_STATIC / "util-tools-markdown.js").read_text(encoding="utf-8")
