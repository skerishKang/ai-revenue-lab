"""Shipped-source readers for capability/CSS/handoff contracts (#8060).

Raw reads live here. The tests keep every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"


def chat_transport_js() -> str:
    return (_STATIC / "chat-transport.js").read_text(encoding="utf-8")


def claw_local_handoff_js() -> str:
    return (_STATIC / "claw-local-handoff.js").read_text(encoding="utf-8")


def read_text(path) -> str:
    return Path(path).read_text(encoding="utf-8")
