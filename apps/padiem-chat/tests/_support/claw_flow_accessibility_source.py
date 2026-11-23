"""Claw-flow accessibility contract raw reads (#8060).

Raw reads live here. Tests assert on parsed attributes, rule bodies and
function values from the returned text. The shared ``claw_static`` helper is
untouched.
"""
from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def app_js() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")


def claw_run_js() -> str:
    return (_STATIC / "chat-claw-run-module.js").read_text(encoding="utf-8")


def claw_form_js() -> str:
    return (_STATIC / "chat-claw-form-module.js").read_text(encoding="utf-8")


def claw_status_js() -> str:
    return (_STATIC / "chat-claw-status-module.js").read_text(encoding="utf-8")


def workspace_css() -> str:
    return (_STATIC / "claw-workspace.css").read_text(encoding="utf-8")
