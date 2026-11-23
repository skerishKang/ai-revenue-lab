"""Static source accessors for the Claw Drive first-use contract (#8060).

Raw reads live here. The test keeps its ownership and user-facing copy
contracts; it never reads a shipped file itself.
"""
from __future__ import annotations

from _support import claw_static


def index_html() -> str:
    return claw_static.sheet("index.html")


def app() -> str:
    return claw_static.sheet("app.js")


def guide() -> str:
    return claw_static.sheet("claw-connection-guide.js")


def chips() -> str:
    return claw_static.sheet("claw-connection-chips.js")


def manager() -> str:
    return claw_static.sheet("claw-drive-account-management.js")


def connectors() -> str:
    return claw_static.sheet("chat-connectors-module.js")
