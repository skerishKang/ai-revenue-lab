"""Source accessors for the chat rhythm contract (#8060).

Raw reads live here. The test keeps its CSS and QA-script checks; it never reads
a shipped file itself.
"""
from __future__ import annotations

from _support import claw_static


def sheet(name: str) -> str:
    return claw_static.sheet(name)


def repo_source(relative: str) -> str:
    return claw_static.repo_source(relative)
