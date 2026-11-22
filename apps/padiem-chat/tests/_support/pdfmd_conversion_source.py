"""Source accessors for the PDF/MD conversion limits (#8060).

Raw reads live here. Tests assert on parsed settings and sheet tokens.
The shared ``claw_static`` helper is untouched.
"""
from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def migration_text(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def sheet_text(name: str) -> str:
    return (_ROOT / "static" / name).read_text(encoding="utf-8")


def sheet_has(name: str, needle: str) -> bool:
    return needle in sheet_text(name)
