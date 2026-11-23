"""Source accessors for the attachment byte-total contract (#8060).

Raw reads live here. The test keeps its source-absence and README checks; it
never reads a shipped file itself.
"""
from __future__ import annotations

from _support import claw_static


def app_source(name: str) -> str:
    return claw_static.server_source(name.removesuffix(".py"))


def sheet(name: str) -> str:
    return claw_static.sheet(name)


def readme() -> str:
    return claw_static.repo_source("apps/padiem-chat/README.md")


def repo_source(relative: str) -> str:
    return claw_static.repo_source(relative)
