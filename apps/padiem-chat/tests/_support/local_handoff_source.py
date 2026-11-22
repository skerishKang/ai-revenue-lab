"""Parsed-source boundary for the #3084 local handoff UI tests.

Raw ``read_text`` lives here; contract tests receive one named view and assert
on computed/parsed values. No runtime behaviour changes.
"""
from __future__ import annotations

from pathlib import Path

import locale_bundle

STATIC = Path(__file__).resolve().parents[2] / "static"


def sheet(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def module() -> str:
    return sheet("claw-local-handoff.js")


def app() -> str:
    return sheet("app.js")


def panel_module() -> str:
    return sheet("chat-local-pc-panel-module.js")


def index() -> str:
    return sheet("index.html")


def locale() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")


def css() -> str:
    return sheet("claw-local-handoff.css")


def named(name: str) -> str:
    return sheet(name)


def ci_workflow() -> str:
    root = Path(__file__).resolve().parents[4]
    return (root / ".github/workflows/b62-padiem-chat-ci.yml").read_text(encoding="utf-8")
