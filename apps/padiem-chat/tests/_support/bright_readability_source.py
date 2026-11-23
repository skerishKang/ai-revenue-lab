"""Bright-readability contract raw reads (#8060).

Raw reads live here. Tests assert on parsed CSS rule/token values from the
returned text. The shared ``claw_static`` helper is untouched.
"""
from __future__ import annotations

from pathlib import Path

_APP = Path(__file__).resolve().parents[2]


def polish_css() -> str:
    return (_APP / "static" / "padiem-bright-readability.css").read_text(encoding="utf-8")


def index_html() -> str:
    return (_APP / "static" / "index.html").read_text(encoding="utf-8")
