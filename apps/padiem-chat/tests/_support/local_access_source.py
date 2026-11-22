"""Parsed-source boundary for the #3094 local access adapter tests.

Raw ``read_text`` lives here; contract tests receive named source views and
assert on parsed values (script order, literal counts, rule presence).
"""
from __future__ import annotations

from pathlib import Path

from _support.local_handoff_source import sheet

ROOT = Path(__file__).resolve().parents[4]
CHAT = ROOT / "apps/padiem-chat"


def adapter() -> str:
    return sheet("claw-local-adapter.js")


def handoff() -> str:
    return sheet("claw-local-handoff.js")


def app() -> str:
    return sheet("app.js")


def panel_module() -> str:
    return sheet("chat-local-pc-panel-module.js")


def index() -> str:
    return sheet("index.html")


def factory() -> str:
    return (CHAT / "app/app_factory.py").read_text(encoding="utf-8")


def ci_workflow() -> str:
    return (ROOT / ".github/workflows/b62-padiem-chat-ci.yml").read_text(encoding="utf-8")


def static_path(name: str) -> str:
    return str(CHAT / "static" / name)
