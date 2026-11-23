"""Shipped-source accessors for Claw screen contracts (#8060).

Raw reads live here. The tests keep every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path

_TESTS = Path(__file__).resolve().parents[1]
_STATIC = _TESTS.parent / "static"
_APP = _TESTS.parent / "app"


def read(path) -> str:
    return Path(path).read_text(encoding="utf-8")


def claw_manager_js() -> str:
    return (_STATIC / "claw-device-manager.js").read_text(encoding="utf-8")


def claw_routes_py() -> str:
    return (_APP / "claw_general_routes.py").read_text(encoding="utf-8")


def app_js() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")


def claw_automation_store_py() -> str:
    return (_APP / "claw_automation_store.py").read_text(encoding="utf-8")
