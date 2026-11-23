"""Static source accessors for the web XLSX P01 browser contract (#8060).

Raw reads live here. The test keeps its markup and behavior checks; it never
reads a shipped file itself.
"""
from __future__ import annotations

from pathlib import Path

from _support import claw_static

_TESTS = Path(__file__).resolve().parents[1]


def sheet(name: str) -> str:
    return claw_static.sheet(name)


def tests_path(name: str) -> str:
    return str(_TESTS / name)
