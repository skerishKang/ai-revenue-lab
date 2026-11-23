"""Source accessors for the PDF/MD PC import/save contracts (#8060).

Raw reads live here. Both tests keep every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path

_CHAT = Path(__file__).resolve().parents[2]
_STATIC = _CHAT / "static"


def util_pdfmd_js() -> str:
    return (_STATIC / "util-pdfmd.js").read_text(encoding="utf-8")


def pc_file_exchange_js() -> str:
    return (_STATIC / "pc-file-exchange.js").read_text(encoding="utf-8")


def util_menu_css() -> str:
    return (_STATIC / "util-menu.css").read_text(encoding="utf-8")


def council_app_js() -> str:
    return (_CHAT.parent / "padiem-council-apps" / "static" / "council-app.js").read_text(encoding="utf-8")


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def util_app_js() -> str:
    return (_STATIC / "util-app.js").read_text(encoding="utf-8")


def util_manifest_js() -> str:
    return (_STATIC / "util-manifest.js").read_text(encoding="utf-8")


def document_convert_routes() -> str:
    return (_CHAT / "app" / "document_convert_routes.py").read_text(encoding="utf-8")


def local_cpython() -> str:
    return (_CHAT / "app" / "local_cpython.py").read_text(encoding="utf-8")
