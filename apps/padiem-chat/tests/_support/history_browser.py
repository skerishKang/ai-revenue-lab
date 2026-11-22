"""Shipped history-forwarder sheets for the R5 step-3 contracts (#8060).

Keeps the raw ``read_text`` calls out of the contract tests: the tests receive
the shipped app source and the strict-deps fixture, with the sheet paths here.
"""
from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"


def static_dir() -> Path:
    return _STATIC


def app_js() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")


def strict_deps_js() -> str:
    return (Path(__file__).resolve().parents[1] / "_r5_strict_deps.js").read_text(encoding="utf-8")
