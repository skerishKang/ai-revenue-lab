"""Shipped-source accessors for R5 browser and golden contracts (#8060).

Raw reads live here. The tests keep every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path

_TESTS = Path(__file__).resolve().parents[1]
_ROOT = _TESTS.parent
_STATIC = _ROOT / "static"


def read(path) -> str:
    return Path(path).read_text(encoding="utf-8")


def app_js() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")


def strict_deps_js() -> str:
    return (_TESTS / "_r5_strict_deps.js").read_text(encoding="utf-8")


def app_context_js() -> str:
    return (_STATIC / "chat-app-context.js").read_text(encoding="utf-8")


def login_golden_json() -> str:
    return (_ROOT / "tests/fixtures/r5_b4_2_login_golden.json").read_text(encoding="utf-8")
