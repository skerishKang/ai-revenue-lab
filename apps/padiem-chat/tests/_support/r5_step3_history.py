"""Shipped history-module sheets for the R5 step-3 contracts (#8060 60차).

Keeps the raw ``read_text`` calls out of the contract tests: the tests receive
the shipped sources and the strict-deps stub text, with the sheet paths here.
"""
from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"
_TESTS = Path(__file__).resolve().parents[2] / "tests"


def static_dir() -> Path:
    """The shipped sheets directory (node harnesses take it as an argument)."""
    return _STATIC


def history_module_path() -> Path:
    return _STATIC / "chat-history-module.js"


def app_source() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")


def history_module_source() -> str:
    return (_STATIC / "chat-history-module.js").read_text(encoding="utf-8")


def run_history_source() -> str:
    return (_STATIC / "chat-run-history-module.js").read_text(encoding="utf-8")


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def strict_deps_text() -> str:
    return (_TESTS / "_r5_strict_deps.js").read_text(encoding="utf-8")
