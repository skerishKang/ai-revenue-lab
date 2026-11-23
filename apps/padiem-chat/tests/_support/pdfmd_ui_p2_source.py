"""Source accessors for the PDF/MD UI phase-2 contract (#8060).

Raw reads live here. The test keeps its source-absence and behavior checks; it
never reads a shipped file itself.
"""
from __future__ import annotations

from pathlib import Path

from _support import claw_static

_TESTS = Path(__file__).resolve().parents[1]
_STATIC = Path(__file__).resolve().parents[2] / "static"


def static_path(name: str) -> str:
    return str(_STATIC / name)


def chat_root() -> str:
    return str(Path(__file__).resolve().parents[2])


def pdfmd_js() -> str:
    return claw_static.sheet("util-pdfmd.js")


def pdfmd_pages_js() -> str:
    return claw_static.sheet("util-pdfmd-pages.js")


def util_menu_css() -> str:
    return claw_static.sheet("util-menu.css")


def tests_path(name: str) -> str:
    return str(_TESTS / name)
