"""Source accessors for the README contract test (#8060).

Raw reads live here. Tests assert on token presence in the shipped files.
The shared ``claw_static`` helper is untouched.
"""
from __future__ import annotations

import locale_bundle
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_STATIC = _ROOT / "static"
_APP = _ROOT / "app"


def readme_text() -> str:
    return (_ROOT / "README.md").read_text(encoding="utf-8")


def locale_text() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")


def sheet_text(name: str) -> str:
    return (_STATIC / name).read_text(encoding="utf-8")


def app_text(name: str) -> str:
    return (_APP / name).read_text(encoding="utf-8")


def root_text(name: str) -> str:
    return (_ROOT / name).read_text(encoding="utf-8")


def readme_has(needle: str) -> bool:
    return needle in readme_text()


def locale_has(needle: str) -> bool:
    return needle in locale_text()


def sheet_has(name: str, needle: str) -> bool:
    return needle in sheet_text(name)


def app_has(name: str, needle: str) -> bool:
    return needle in app_text(name)


def root_has(name: str, needle: str) -> bool:
    return needle in root_text(name)
