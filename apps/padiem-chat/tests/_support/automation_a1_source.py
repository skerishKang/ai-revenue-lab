"""Static source accessors for the R5 A1 automation module contract (#8060).

Raw sheet reads live here. The test module asserts on ownership structure,
parsed script order and the Node VM behavior; it never reads a shipped sheet
itself.
"""
from __future__ import annotations

from pathlib import Path

from _support import claw_static

_TESTS = Path(__file__).resolve().parents[1]
_STATIC = Path(__file__).resolve().parents[2] / "static"


def sheet_path(name: str) -> str:
    """Absolute shipped-sheet path for the Node VM harness."""
    return str(_STATIC / name)


def app_source() -> str:
    return claw_static.sheet("app.js")


def context_source() -> str:
    return claw_static.sheet("chat-app-context.js")


def automation_module_source() -> str:
    return claw_static.sheet("chat-automation-module.js")


def automation_form_source() -> str:
    return claw_static.sheet("chat-automation-form-module.js")


def index_source() -> str:
    return claw_static.sheet("index.html")


def nav_module_source() -> str:
    return claw_static.sheet("chat-nav-module.js")


def strict_deps_source() -> str:
    """The test-side strict deps fixture, not a shipped sheet."""
    return (_TESTS / "_r5_strict_deps.js").read_text(encoding="utf-8")
