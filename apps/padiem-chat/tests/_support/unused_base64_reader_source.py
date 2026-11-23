"""Static source accessors for the removed Base64 reader guard (#8060).

Raw reads live here. The test keeps its absence and locale-parity checks; it
never reads a shipped file itself.
"""
from __future__ import annotations

import locale_bundle
from _support import claw_static


def sheet(name: str) -> str:
    return claw_static.sheet(name)


def locale_source() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")
