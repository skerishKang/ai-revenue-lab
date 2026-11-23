"""Shipped-source accessors for transport contracts (#8060).

Raw reads live here. The tests keep every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path

_TESTS = Path(__file__).resolve().parents[1]
_STATIC = _TESTS.parent / "static"
_REACT = _TESTS.parent.parent / "padiem-chat-react" / "src"


def read(path) -> str:
    return Path(path).read_text(encoding="utf-8")


def transport_js() -> str:
    return (_STATIC / "chat-transport.js").read_text(encoding="utf-8")


def streaming_module_js() -> str:
    return (_STATIC / "chat-streaming-module.js").read_text(encoding="utf-8")


def app_js() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")


def pc_recovery_js() -> str:
    return (_STATIC / "chat-pc-result-recovery.js").read_text(encoding="utf-8")


def react_transport_ts() -> str:
    return (_REACT / "lib" / "chat-transport.ts").read_text(encoding="utf-8")


def react_claw_ts() -> str:
    return (_REACT / "api" / "clawApi.ts").read_text(encoding="utf-8")
