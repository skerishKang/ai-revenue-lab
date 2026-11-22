"""Shipped-source reads for the B62 Glass home/chat parity contracts.

The raw ``read_text`` calls live here (reusing claw_static); the contract test
keeps its parsed-block scans and computed offender lists but holds no raw
source read of its own.
"""
from __future__ import annotations

from pathlib import Path

from _support.claw_static import sheet

STATIC = Path(__file__).resolve().parents[2] / "static"


def css_text(name: str) -> str:
    return sheet(name)


def tokens_text() -> str:
    return sheet("padiem-tokens.css")


def markup_text() -> str:
    return sheet("index.html")


def js_text(name: str) -> str:
    return sheet(name)


def all_css_sheets() -> list[tuple[str, str]]:
    """(basename, text) for every shipped CSS sheet, in filename order."""
    return [(path.name, path.read_text(encoding="utf-8")) for path in sorted(STATIC.glob("*.css"))]
