"""Shipped-source accessors for android/pairing/audio contracts (#8060).

Raw reads live here. The tests keep every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path

import locale_bundle

_STATIC = Path(__file__).resolve().parents[2] / "static"


def read(name: str) -> str:
    return (_STATIC / name).read_text(encoding="utf-8")


def locale_source() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")


def pc_pairing_card_js() -> str:
    return (_STATIC / "pc-pairing-card.js").read_text(encoding="utf-8")


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def meeting_capture_js() -> str:
    return (_STATIC / "meeting-capture.js").read_text(encoding="utf-8")
