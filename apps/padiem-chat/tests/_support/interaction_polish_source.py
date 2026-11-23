"""Interaction-polish contract raw reads (#8060).

Raw reads live here. Tests assert on parsed tokens and rule values from the
returned text. The shared ``claw_static`` helper is untouched.
"""
from __future__ import annotations

from pathlib import Path

_APP = Path(__file__).resolve().parents[2]


def interaction_js() -> str:
    return (_APP / "static" / "interaction-polish.js").read_text(encoding="utf-8")


def interaction_css() -> str:
    return (_APP / "static" / "interaction-polish.css").read_text(encoding="utf-8")


def outputs_js() -> str:
    return (_APP / "static" / "outputs.js").read_text(encoding="utf-8")


def export_js() -> str:
    return (_APP / "static" / "conversation-export.js").read_text(encoding="utf-8")


def a11y_js() -> str:
    return (_APP / "static" / "a11y.js").read_text(encoding="utf-8")


def index_html() -> str:
    return (_APP / "static" / "index.html").read_text(encoding="utf-8")
