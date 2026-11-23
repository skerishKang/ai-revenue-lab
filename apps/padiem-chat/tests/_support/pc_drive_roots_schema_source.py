"""Source accessor for the PC drive-roots schema contract (#8060).

The raw read lives here. The test keeps its path-not-found stage assertion; it
never reads a shipped file itself.
"""
from __future__ import annotations

from _support import claw_static


def query_step_driver() -> str:
    return claw_static.repo_source("apps/padiem-ai-engine/app/claw_pc_query_step_driver.py")
