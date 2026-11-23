"""Static source accessors for the mobile target legibility contract (#8060).

Raw reads live here. The test keeps its markup, CSS, locale, browser-measurement
and floor assertions; it never reads a shipped file itself.
"""
from __future__ import annotations

from pathlib import Path

import locale_bundle
from _support import claw_static

_STATIC = Path(__file__).resolve().parents[2] / "static"


def sheet(name: str) -> str:
    return claw_static.sheet(name)


def locale_source() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")


def static_dir() -> str:
    return str(_STATIC)
