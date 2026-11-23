"""Shipped-source accessors for foundation and deep-ink token contracts (#8060).

Raw reads live here. The tests keep every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"


def read(path) -> str:
    return Path(path).read_text(encoding="utf-8")


def read_static(name: str) -> str:
    return (_STATIC / name).read_text(encoding="utf-8")


def tokens_css() -> str:
    return (_STATIC / "padiem-tokens.css").read_text(encoding="utf-8")


def foundation_css() -> str:
    return (_STATIC / "padiem-foundation.css").read_text(encoding="utf-8")


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")
