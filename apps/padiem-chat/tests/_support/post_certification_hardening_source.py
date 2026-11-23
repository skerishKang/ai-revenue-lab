"""Source accessors for the post-certification hardening contract (#8060).

Raw reads live here. The test keeps its source and workflow assertions; it never
reads a shipped file itself.
"""
from __future__ import annotations

from _support import claw_static


def qa_script() -> str:
    return claw_static.repo_source(".github/scripts/b62_post_certification_browser_qa.py")


def workflow() -> str:
    return claw_static.repo_source(".github/workflows/b62-browser-qa-unified.yml")


def sheet(name: str) -> str:
    return claw_static.sheet(name)
