"""Shipped sources for the #5568 PDF/MD UI contracts (#8060).

Raw ``read_text`` lives here so the contract tests take source text through a
helper instead of pinning where the files sit.
"""
from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"


def pdfmd_js_source() -> str:
    return (_STATIC / "util-pdfmd.js").read_text(encoding="utf-8")


def pdfmd_pages_js_source() -> str:
    return (_STATIC / "util-pdfmd-pages.js").read_text(encoding="utf-8")


def util_menu_css_source() -> str:
    return (_STATIC / "util-menu.css").read_text(encoding="utf-8")
