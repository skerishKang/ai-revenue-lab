"""Shipped saved-outputs sheets for the truthfulness contracts (#8060).

Keeps the raw ``read_text`` calls out of the contract tests: the tests receive
the shipped sources and the migration text, with the file paths here.
"""
from __future__ import annotations

from pathlib import Path

_CHAT = Path(__file__).resolve().parents[2]


def index_html() -> str:
    return (_CHAT / "static/index.html").read_text(encoding="utf-8")


def outputs_js() -> str:
    return (_CHAT / "static/outputs.js").read_text(encoding="utf-8")


def a11y_js() -> str:
    return (_CHAT / "static/a11y.js").read_text(encoding="utf-8")


def worker_py() -> str:
    return (_CHAT / "worker.py").read_text(encoding="utf-8")


def saved_outputs_migration() -> str:
    return (_CHAT / "migrations/004_saved_outputs.sql").read_text(encoding="utf-8")
