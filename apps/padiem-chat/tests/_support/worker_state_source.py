"""Source accessor for the #7543 worker-state regression guard.

The raw read lives here so the guard test only asserts on returned text.
"""
from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"


def pending_result_poll_source() -> str:
    return (_STATIC / "chat-pc-run-module.js").read_text(encoding="utf-8")
