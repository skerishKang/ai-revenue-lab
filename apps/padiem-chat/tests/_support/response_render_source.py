"""Shipped-source accessors for response rendering contracts (#8060).

Raw reads live here. The tests keep every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path

_TESTS = Path(__file__).resolve().parents[1]
_STATIC = _TESTS.parent / "static"
_APP = _TESTS.parent / "app"


def read(path) -> str:
    return Path(path).read_text(encoding="utf-8")


def search_sources_js() -> str:
    return (_STATIC / "search-sources.js").read_text(encoding="utf-8")


def rich_response_js() -> str:
    return (_STATIC / "rich-response.js").read_text(encoding="utf-8")


def rich_css() -> str:
    return (_STATIC / "padiem-rich.css").read_text(encoding="utf-8")


def search_css() -> str:
    return (_STATIC / "search-sources.css").read_text(encoding="utf-8")


def tokens_css() -> str:
    return (_STATIC / "padiem-tokens.css").read_text(encoding="utf-8")


def request_contract_py() -> str:
    return (_APP / "request_contract.py").read_text(encoding="utf-8")
