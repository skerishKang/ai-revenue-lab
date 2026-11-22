"""Shipped login-modal sheets for the #5481 contracts (#8060).

Keeps the raw ``read_text`` calls out of the contract tests: the tests receive
the shipped sources and the locale sheet text, with the sheet paths here.
"""
from __future__ import annotations

import locale_bundle

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def script_source() -> str:
    """The auth views span the auth and account modules (both shipped sources)."""
    return ((_STATIC / "app.js").read_text(encoding="utf-8")
            + (_STATIC / "chat-auth-module.js").read_text(encoding="utf-8")
            + (_STATIC / "chat-account-module.js").read_text(encoding="utf-8"))


def styles_source() -> str:
    return (_STATIC / "history.css").read_text(encoding="utf-8")


def locale_source() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")
