"""Shipped source sheets for the P01 routing contracts (#8060 47차).

Keeps the raw ``read_text`` calls out of the routing contract test. This module
is deliberately separate from ``claw_general_routing`` (the #8061 prep hub) so
touching these sheets does not widen that hub's blast radius.
"""
from __future__ import annotations

from pathlib import Path

_CHAT = Path(__file__).resolve().parents[2]


def _shipped(relative: str) -> str:
    return (_CHAT / relative).read_text(encoding="utf-8")


def claw_general_routes_source() -> str:
    return _shipped("app/claw_general_routes.py")


def app_factory_source() -> str:
    return _shipped("app/app_factory.py")


def app_js_source() -> str:
    return _shipped("static/app.js")


def transport_source() -> str:
    return _shipped("static/chat-transport.js")


def streaming_module_source() -> str:
    return _shipped("static/chat-streaming-module.js")
