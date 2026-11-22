"""Shipped orchestration-lifecycle sheets for the B62 contracts (#8060).

Keeps the raw ``read_text`` calls out of the contract tests: the tests receive
the shipped browser sources and the shared Core event kinds source, with the
sheet paths here.
"""
from __future__ import annotations

from pathlib import Path

_CHAT = Path(__file__).resolve().parents[2]
_STATIC = _CHAT / "static"
_CORE_EVENTS = _CHAT.parents[1] / "packages" / "padiem-ai-core" / "padiem_ai_core" / "orchestration_events.py"


def message_lifecycle_source() -> str:
    return (_STATIC / "message-lifecycle.js").read_text(encoding="utf-8")


def transport_source() -> str:
    return (_STATIC / "chat-transport.js").read_text(encoding="utf-8")


def core_events_source() -> str:
    return _CORE_EVENTS.read_text(encoding="utf-8")
