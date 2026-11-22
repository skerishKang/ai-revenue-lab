"""Saved PC-form contract raw reads (#8060).

Raw reads live here. Tests assert on parsed values and tokens from the
returned text. The shared ``claw_static`` helper is untouched.
"""
from __future__ import annotations

from pathlib import Path

_APP = Path(__file__).resolve().parents[2]


def migration_sql(name: str) -> str:
    return (_APP / "migrations" / name).read_text(encoding="utf-8")


def quote_runtime_script() -> str:
    return (_APP / "static" / "b66-quote-runtime.js").read_text(encoding="utf-8")
