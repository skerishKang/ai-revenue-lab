"""Source accessors for the PDF/MD failure-copy contract (#8060).

Raw reads live here. The test keeps its migration behavior and user-facing copy
contracts; it never reads a shipped file itself.
"""
from __future__ import annotations

from _support import claw_static


def migration(name: str) -> str:
    return claw_static.migration_source(name)


def pdfmd_js() -> str:
    return claw_static.sheet("util-pdfmd.js")
