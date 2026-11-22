"""Shipped quote-PC-import sheets for the #6460 contracts (#8060).

Keeps the raw ``read_text`` calls out of the contract tests: the tests receive
the shipped page and module sheets through this reader, with the sheet paths
kept in the tests.
"""
from __future__ import annotations

from pathlib import Path


def read_sheet(path: Path) -> str:
    return path.read_text(encoding="utf-8")
