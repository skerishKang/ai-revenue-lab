"""PDF/MD PC-exchange contract raw reads (#8060).

Raw reads live here. Tests assert on parsed tokens and values from the
returned text. The shared ``claw_static`` helper is untouched.
"""
from __future__ import annotations

from pathlib import Path

_APP = Path(__file__).resolve().parents[2]


def pdfmd_js() -> str:
    return (_APP / "static" / "util-pdfmd.js").read_text(encoding="utf-8")


def exchange_js() -> str:
    return (_APP / "static" / "pc-file-exchange.js").read_text(encoding="utf-8")


def convert_routes_source() -> str:
    return (_APP / "app" / "document_convert_routes.py").read_text(encoding="utf-8")
