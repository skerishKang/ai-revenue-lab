"""Shipped claw-run browser sheets for the R5 A5A contracts (#8060).

Keeps the raw ``read_text`` calls out of the contract tests: the tests receive
the shipped app source, with the sheet path here.
"""
from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"


def static_dir() -> Path:
    return _STATIC


def app_js() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")
