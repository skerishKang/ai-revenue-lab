"""Source accessors for the #5895 PC wait and stream-loss wiring tests (#8060).

Raw reads live here. Both contract tests keep their assertions and receive
shipped text through these accessors.
"""
from __future__ import annotations

from pathlib import Path

from _support import claw_static

_STATIC = Path(__file__).resolve().parents[2] / "static"
_TESTS = Path(__file__).resolve().parents[1]


def recovery_js() -> str:
    return claw_static.sheet("chat-pc-result-recovery.js")


def streaming_js() -> str:
    return claw_static.sheet("chat-streaming-module.js")


def locale_js() -> str:
    return claw_static.locale_source()


def static_dir() -> str:
    return str(_STATIC)


def node_test_path(name: str) -> Path:
    return _TESTS / name
