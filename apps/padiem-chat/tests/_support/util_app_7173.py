"""Shipped Util-app sheets for the #7173 contracts (#8060).

Keeps the raw ``read_text`` calls out of the contract tests: the tests receive
the shipped sources, with the sheet paths here.
"""
from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def util_manifest_js() -> str:
    return (_STATIC / "util-manifest.js").read_text(encoding="utf-8")


def util_app_js() -> str:
    return (_STATIC / "util-app.js").read_text(encoding="utf-8")


def util_app_css() -> str:
    return (_STATIC / "util-app.css").read_text(encoding="utf-8")


def app_js() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")
