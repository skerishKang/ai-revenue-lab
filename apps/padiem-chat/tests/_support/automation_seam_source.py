"""Source accessors for the async automation composition seam (#8060).

Raw reads live here. Tests assert on parsed config values and source tokens.
The shared ``claw_static`` helper is untouched.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

_CHAT = Path(__file__).resolve().parents[2]


def read_text(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def worker_source() -> str:
    return (_CHAT / "worker.py").read_text(encoding="utf-8")


def wrangler_source() -> str:
    return (_CHAT / "wrangler.toml").read_text(encoding="utf-8")


def wrangler_triggers() -> dict:
    return tomllib.loads(wrangler_source()).get("triggers")


def discovery_source() -> str:
    return (_CHAT / "app" / "claw_automation_due_workspace_discovery.py").read_text(encoding="utf-8")
