"""Static source accessors for the L2 result file card contract (#8060).

Raw reads live here. The test keeps the shipped renderer's parsed definition,
locale-copy ownership and the Node behavioral harness; it never reads a shipped
file itself.
"""
from __future__ import annotations

from pathlib import Path

import locale_bundle
from _support import claw_static

_STATIC = Path(__file__).resolve().parents[2] / "static"


def app_source() -> str:
    return claw_static.sheet("app.js")


def run_module_source() -> str:
    return claw_static.sheet("chat-claw-run-module.js")


def locale_source() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")


def workspace_css() -> str:
    return claw_static.sheet("claw-workspace.css")


def run_history_module_path() -> str:
    """Absolute path the behavioral harness loads as the real renderer module."""
    return str(_STATIC / "chat-run-history-module.js")
