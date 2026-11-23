"""Source accessors for the login free-hint contract (#8060).

Raw reads live here. The test keeps its locale and route checks; it never reads
a shipped file itself.
"""
from __future__ import annotations

import locale_bundle
from _support import claw_static


def sheet(name: str) -> str:
    return claw_static.sheet(name)


def locale_source() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")


def chat_routes() -> str:
    return claw_static.server_source("chat_routes")
