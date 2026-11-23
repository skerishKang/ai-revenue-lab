"""Migration accessors for the history workspace linkage contract (#8060).

Raw reads live here. The test keeps its additive-column assertions; it never
reads a shipped file itself.
"""
from __future__ import annotations

from pathlib import Path

from _support import claw_static

_MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"


def migration_names() -> list[str]:
    return sorted(path.name for path in _MIGRATIONS.glob("*.sql"))


def migration(name: str) -> str:
    return claw_static.migration_source(name)
