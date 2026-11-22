"""Connector-management contract accessors (#8060).

Raw reads live here. Tests assert on parsed HTML ids/attributes/script order
and sheet token presence. The shared ``claw_static`` helper is untouched.
"""
from __future__ import annotations

from pathlib import Path

from _support.html_tags import tags_for_page

_STATIC = Path(__file__).resolve().parents[2] / "static"


def sheet_text(name: str) -> str:
    return (_STATIC / name).read_text(encoding="utf-8")


def sheet_has(name: str, needle: str) -> bool:
    return needle in sheet_text(name)


def html_ids() -> set[str]:
    return {attrs["id"] for _tag, attrs in tags_for_page("index.html") if "id" in attrs}


def html_has_attr(attr: str, value: str) -> bool:
    return any(attrs.get(attr) == value for _tag, attrs in tags_for_page("index.html"))


def script_srcs() -> list[str]:
    return [attrs["src"] for tag, attrs in tags_for_page("index.html")
            if tag == "script" and "src" in attrs]
