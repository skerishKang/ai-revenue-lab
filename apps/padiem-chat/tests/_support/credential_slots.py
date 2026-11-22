"""Shipped credential-slots sheets for the admin contracts (#8060).

Keeps the raw ``read_text`` calls out of the contract tests: the tests receive
the shipped page and script sheets, with the sheet paths here.
"""
from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"


def static_asset(filename: str) -> str:
    return (_STATIC / filename).read_text(encoding="utf-8")
