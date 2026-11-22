"""Composer device-band accessors (#8060).

Raw reads live here. Tests assert on parsed CSS rule bodies and JS tokens.
The shared ``claw_static`` helper is untouched.
"""
from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"


def read_text(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def all_css_texts() -> list[tuple[str, str]]:
    return [(path.name, path.read_text(encoding="utf-8"))
            for path in sorted(_STATIC.glob("*.css"))]


def status_css() -> str:
    return (_STATIC / "claw-composer-connection-status.css").read_text(encoding="utf-8")


def status_js() -> str:
    return (_STATIC / "claw-composer-connection-status.js").read_text(encoding="utf-8")
