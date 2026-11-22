"""Parsed/tokenized views for the #5108 admin hub contracts (#8060).

Raw file reads live here. Tests receive tokenized source sets and computed
presence checks. The shared ``claw_static`` helper is reused for shipped sheets.
"""
from __future__ import annotations

import re
from pathlib import Path

from _support.claw_static import sheet

_STRING_RX = re.compile(r'"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\'')
_IDENTIFIER_RX = re.compile(r"[A-Za-z_$][\w$]*")


def source(path: Path) -> str:
    """Read a source file (path stays in the test, raw read lives here)."""
    return path.read_text(encoding="utf-8")


def static_source(name: str) -> str:
    return sheet(name)


def tokens(path: Path) -> set[str]:
    text = source(path)
    identifiers = set(_IDENTIFIER_RX.findall(text))
    strings = {double or single for double, single in _STRING_RX.findall(text)}
    return identifiers | strings


def has(path: Path, fragment: str) -> bool:
    """Whitespace-normalized line contains the fragment."""
    return any(
        fragment in re.sub(r"\s+", " ", line).strip()
        for line in source(path).splitlines()
    )


def lacks(path: Path, fragment: str) -> bool:
    return not has(path, fragment)
