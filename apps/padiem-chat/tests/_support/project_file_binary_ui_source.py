"""Project-file binary UI contract raw reads (#8060).

Raw reads live here. Tests assert on parsed tokens and attribute values from
the returned text. The shared ``claw_static`` helper is untouched.
"""
from __future__ import annotations

from pathlib import Path

_APP = Path(__file__).resolve().parents[2]


def index_html() -> str:
    return (_APP / "static" / "index.html").read_text(encoding="utf-8")


def licenses_html() -> str:
    return (_APP / "static" / "third-party-licenses.html").read_text(encoding="utf-8")


def app_js() -> str:
    return (_APP / "static" / "app.js").read_text(encoding="utf-8")


def tus_module_js() -> str:
    return (_APP / "static" / "project-file-upload.js").read_text(encoding="utf-8")


def tus_upload_js() -> str:
    return (_APP / "static" / "tus-upload.js").read_text(encoding="utf-8")


def documents_css() -> str:
    return (_APP / "static" / "documents.css").read_text(encoding="utf-8")


def polish_css() -> str:
    return (_APP / "static" / "accessibility-polish.css").read_text(encoding="utf-8")
