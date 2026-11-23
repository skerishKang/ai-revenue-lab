"""Shipped-source readers for PC-command/ops/route contracts (#8060).

Raw reads live here. The tests keep every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"


def read(path) -> str:
    return Path(path).read_text(encoding="utf-8")


def pc_command_ready_js() -> str:
    return (_STATIC / "pc-command-ready.js").read_text(encoding="utf-8")


def pc_pairing_card_css() -> str:
    return (_STATIC / "pc-pairing-card.css").read_text(encoding="utf-8")


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def admin_html() -> str:
    return (_STATIC / "admin.html").read_text(encoding="utf-8")


def admin_ops_js() -> str:
    return (_STATIC / "admin-ops.js").read_text(encoding="utf-8")


def admin_css() -> str:
    return (_STATIC / "admin.css").read_text(encoding="utf-8")
