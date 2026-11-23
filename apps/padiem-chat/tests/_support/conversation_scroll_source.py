"""Static source accessors for the shared conversation scroll contract (#8060).

Raw sheet and locale reads live here. The test keeps its behavior observation
and source-ownership contracts; it never reads a shipped file itself.
"""
from __future__ import annotations

import locale_bundle
from _support import claw_static


def source(name: str) -> str:
    return claw_static.sheet(name)


def locale_source() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")
