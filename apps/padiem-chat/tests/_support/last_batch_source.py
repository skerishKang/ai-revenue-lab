"""Shipped-source accessors for last-batch contracts (#8060).

Raw reads live here. The tests keep every assertion unchanged.
"""
from __future__ import annotations

import json
from pathlib import Path

_TESTS = Path(__file__).resolve().parents[1]
_STATIC = _TESTS.parent / "static"
_APP = _TESTS.parent / "app"
_ROOT = _TESTS.parent
_REPO = _TESTS.parent.parent.parent


def read(path) -> str:
    return Path(path).read_text(encoding="utf-8")


def read_replace(path) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")


def xlsx_migration_sql() -> str:
    return (_ROOT / "migrations" / "029_claw_web_xlsx_selection.sql").read_text(encoding="utf-8")


def xlsx_store_py() -> str:
    return (_APP / "claw_web_xlsx_selection_store.py").read_text(encoding="utf-8")


def xlsx_sources_js() -> str:
    return (_STATIC / "claw-web-xlsx-sources.js").read_text(encoding="utf-8")


def locale_js() -> str:
    import locale_bundle

    return locale_bundle.SOURCE.read_text(encoding="utf-8")


def quote_runtime_js() -> str:
    return (_STATIC / "b66-quote-runtime.js").read_text(encoding="utf-8")


def app_js() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")


def strict_deps_js() -> str:
    return (_TESTS / "_r5_strict_deps.js").read_text(encoding="utf-8")


def pylock_toml() -> str:
    return (_ROOT / "pylock.toml").read_text(encoding="utf-8")


def uv_lock_toml() -> str:
    return (_ROOT / "uv.lock").read_text(encoding="utf-8")
