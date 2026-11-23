"""Static source accessors for the Gemini live-voice contract (#8060).

Raw reads live here. The test keeps its source and behavior checks; it never
reads a shipped file itself.
"""
from __future__ import annotations

from pathlib import Path

from _support import claw_static

_STATIC = Path(__file__).resolve().parents[2] / "static"


def sheet(name: str) -> str:
    return claw_static.sheet(name)


def static_path(name: str) -> str:
    return str(_STATIC / name)


def chat_root() -> str:
    return str(Path(__file__).resolve().parents[2])
