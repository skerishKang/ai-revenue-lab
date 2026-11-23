"""Static source accessors for the BYOK simple form contract (#8060).

Raw reads live here. The test keeps its locale ownership and capability copy
contracts; it never reads a shipped file itself.
"""
from __future__ import annotations

import locale_bundle
from _support import claw_static


def locale_source() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")


def capabilities_js() -> str:
    return claw_static.sheet("product-capabilities.js")
