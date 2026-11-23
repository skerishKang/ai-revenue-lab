"""Static source accessors for the Claw P0 UX contract (#8060).

Raw reads live here. The test keeps its token, transport and locale-copy
contracts; it never reads a shipped file itself.
"""
from __future__ import annotations

import locale_bundle
from _support import claw_static


def app() -> str:
    return claw_static.sheet("app.js")


def form() -> str:
    return claw_static.sheet("chat-claw-form-module.js")


def index() -> str:
    return claw_static.sheet("index.html")


def locale() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")


def workspace_css() -> str:
    return claw_static.sheet("claw-workspace.css")


def intake_css() -> str:
    return claw_static.sheet("claw-manual-intake.css")


def memory_module() -> str:
    return claw_static.sheet("chat-memory-module.js")


def core_module() -> str:
    return claw_static.sheet("chat-core-module.js")
