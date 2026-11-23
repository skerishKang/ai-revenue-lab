"""PC command-ready UI contract raw reads (#8060).

Raw reads live here. Tests assert on parsed values and line counts from the
returned text. The shared ``claw_static`` helper is untouched.
"""
from __future__ import annotations

from pathlib import Path

_APP = Path(__file__).resolve().parents[2]


def module_js() -> str:
    return (_APP / "static" / "pc-command-ready.js").read_text(encoding="utf-8")


def card_js() -> str:
    return (_APP / "static" / "pc-pairing-card.js").read_text(encoding="utf-8")


def locale_js() -> str:
    return (_APP / "static" / "locale.js").read_text(encoding="utf-8")
