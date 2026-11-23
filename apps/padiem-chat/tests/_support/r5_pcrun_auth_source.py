"""Shipped-source accessors for R5 pc-run and auth contracts (#8060).

Raw reads live here. The tests keep every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path

_TESTS = Path(__file__).resolve().parents[1]
_STATIC = _TESTS.parent / "static"


def read(path) -> str:
    return Path(path).read_text(encoding="utf-8")


def app_js() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def strict_deps_js() -> str:
    return (_TESTS / "_r5_strict_deps.js").read_text(encoding="utf-8")


def pc_run_module_js() -> str:
    return (_STATIC / "chat-pc-run-module.js").read_text(encoding="utf-8")


def claw_status_module_js() -> str:
    return (_STATIC / "chat-claw-status-module.js").read_text(encoding="utf-8")
