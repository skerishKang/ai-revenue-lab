"""Shipped-source accessors for locale contracts (#8060).

Raw reads live here. The tests keep every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path

_TESTS = Path(__file__).resolve().parents[1]
_STATIC = _TESTS.parent / "static"
_REPO = _TESTS.parent.parent.parent


def read(path) -> str:
    return Path(path).read_text(encoding="utf-8")


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def locale_js() -> str:
    return (_STATIC / "locale.js").read_text(encoding="utf-8")


def pc_ready_js() -> str:
    return (_STATIC / "pc-command-ready.js").read_text(encoding="utf-8")


def consent_html() -> str:
    return (_STATIC / "mcp-oauth-consent.html").read_text(encoding="utf-8")


def privacy_html() -> str:
    return (_STATIC / "privacy.html").read_text(encoding="utf-8")


def terms_html() -> str:
    return (_STATIC / "terms.html").read_text(encoding="utf-8")


def council_app_js() -> str:
    return (_REPO / "apps" / "padiem-council-apps" / "static" / "council-app.js").read_text(encoding="utf-8")
