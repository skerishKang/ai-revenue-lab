"""Source accessors for the Chat PC recovery wiring contract (#8060).

Raw reads live here. The test keeps its source-absence and Node behavior checks;
it never reads a shipped file itself.
"""
from __future__ import annotations

from pathlib import Path

from _support import claw_static

_STATIC = Path(__file__).resolve().parents[2] / "static"
_TESTS = Path(__file__).resolve().parents[1]
_CHAT = Path(__file__).resolve().parents[2]


def sheet(name: str) -> str:
    return claw_static.sheet(name)


def server_source(name: str) -> str:
    return claw_static.server_source(name.removesuffix(".py"))


def static_path(name: str) -> str:
    return str(_STATIC / name)


def static_dir() -> str:
    return str(_STATIC)


def tests_path(name: str) -> str:
    return str(_TESTS / name)


def chat_root() -> str:
    return str(_CHAT)
