"""Shipped sources for the #7839 bookai feedback contracts."""
from __future__ import annotations

from pathlib import Path

_CHAT_STATIC = Path(__file__).resolve().parents[2] / "static"
_BOOKAI = Path(__file__).resolve().parents[3] / "bookai" / "public"


def admin_ops_source() -> str:
    return (_CHAT_STATIC / "admin-ops.js").read_text(encoding="utf-8")


def bookai_index_source() -> str:
    return (_BOOKAI / "index.html").read_text(encoding="utf-8")
