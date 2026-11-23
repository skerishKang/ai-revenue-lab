"""Source accessors for the documents contract (#8060).

Raw reads live here. The test keeps its markup and schema checks; it never reads
a shipped file itself.
"""
from __future__ import annotations

from _support import claw_static


def sheet(name: str) -> str:
    return claw_static.sheet(name)


def migration(name: str) -> str:
    return claw_static.migration_source(name)
