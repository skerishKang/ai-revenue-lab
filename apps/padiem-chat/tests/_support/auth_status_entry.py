"""Shipped auth-status entry-point sheets for the #5479 contracts (#8060 35차).

Keeps the raw ``read_text`` calls out of the contract tests: the tests receive
the shipped sources and the locale sheet text, with the sheet paths here.
"""
from __future__ import annotations

import locale_bundle

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"


def app_source() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")


def auth_module_source() -> str:
    return (_STATIC / "chat-auth-module.js").read_text(encoding="utf-8")


def capabilities_source() -> str:
    return (_STATIC / "product-capabilities.js").read_text(encoding="utf-8")


def outputs_source() -> str:
    return (_STATIC / "outputs.js").read_text(encoding="utf-8")


def locale_source() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")


def password_auth_source() -> str:
    """The server-side password auth module (the session contract check)."""
    return (_STATIC.parent / "app" / "password_auth.py").read_text(encoding="utf-8")
