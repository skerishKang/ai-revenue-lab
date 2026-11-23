"""Source accessor for the Claw PC enrollment consent contract (#8060).

The raw read lives here. The test keeps every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"


def consent_js() -> str:
    return (_STATIC / "claw-pc-enrollment-consent.js").read_text(encoding="utf-8")
