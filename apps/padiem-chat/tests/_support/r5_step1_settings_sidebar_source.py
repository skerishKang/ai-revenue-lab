"""Source accessors for the R5 step-1 settings/sidebar contract (#8060).

Raw reads live here. The test keeps its forwarder and browser checks; it never
reads a shipped file itself.
"""
from __future__ import annotations

from pathlib import Path

from _support import claw_static

_STATIC = Path(__file__).resolve().parents[2] / "static"
_TESTS = Path(__file__).resolve().parents[1]


def app() -> str:
    return claw_static.sheet("app.js")


def strict_deps() -> str:
    return (_TESTS / "_r5_strict_deps.js").read_text(encoding="utf-8")


def chat_dir() -> str:
    return str(_STATIC.parent)


def harness_path() -> str:
    return str(_TESTS / "_r5_forwarder_harness.html")
