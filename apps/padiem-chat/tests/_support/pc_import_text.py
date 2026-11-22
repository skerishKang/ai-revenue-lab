"""Shipped Util PC-import sheets for the #7502 contracts (#8060).

Keeps the raw ``read_text`` calls out of the contract tests: the tests receive
the shipped tool, mode, manifest, locale and style sheets, with the sheet
paths here.
"""
from __future__ import annotations

import locale_bundle

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"


def static_dir() -> Path:
    return _STATIC


def tools_js() -> str:
    return (_STATIC / "util-tools.js").read_text(encoding="utf-8")


def chat_mode_js() -> str:
    return (_STATIC / "util-chat-mode.js").read_text(encoding="utf-8")


def manifest_js() -> str:
    return (_STATIC / "util-manifest.js").read_text(encoding="utf-8")


def locale_source() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")


def tools_css() -> str:
    return (_STATIC / "util-tools.css").read_text(encoding="utf-8")


def chat_css() -> str:
    return (_STATIC / "util-chat-mode.css").read_text(encoding="utf-8")


def app_js() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")
