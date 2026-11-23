"""Source accessors for the Claw model-hold copy contract (#8060).

Raw reads live here. The test keeps every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path

import locale_bundle

_STATIC = Path(__file__).resolve().parents[2] / "static"


def app_js() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")


def stream_js() -> str:
    return (_STATIC / "chat-streaming-module.js").read_text(encoding="utf-8")


def transport_js() -> str:
    return (_STATIC / "chat-transport.js").read_text(encoding="utf-8")


def locale_source() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")
