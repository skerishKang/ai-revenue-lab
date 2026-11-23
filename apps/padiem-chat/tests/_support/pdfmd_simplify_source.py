"""Static source accessors for the PDF/MD simplify contract (#8060).

Raw reads live here. The test keeps its parsed CSS and source-absence checks;
it never reads a shipped file itself.
"""
from __future__ import annotations

from pathlib import Path

from _support import claw_static

_STATIC = Path(__file__).resolve().parents[2] / "static"


def pdfmd_js() -> str:
    return claw_static.sheet("util-pdfmd.js")


def util_menu_css() -> str:
    return claw_static.sheet("util-menu.css")


def static_dir() -> str:
    return str(_STATIC)
