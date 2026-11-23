"""Tus-upload UI contract raw reads (#8060).

Raw reads live here. Tests assert on parsed tokens and counts from the
returned text. The shared ``claw_static`` helper is untouched.
"""
from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"


def read(name: str) -> str:
    return (_STATIC / name).read_text(encoding="utf-8")
