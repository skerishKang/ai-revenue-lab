"""Source accessors for the removed owner model preview contract (#8060).

Raw reads live here. The test keeps its route-absence, asset-absence and copy
contracts; it never reads a shipped file itself.
"""
from __future__ import annotations

from pathlib import Path

import locale_bundle
from _support import claw_static

_STATIC = Path(__file__).resolve().parents[2] / "static"


def app_source(name: str) -> str:
    return claw_static.server_source(name)


def index_html() -> str:
    return claw_static.sheet("index.html")


def static_js_texts() -> list[tuple[str, str]]:
    """(basename, text) for every shipped static JS sheet."""
    return [(path.name, path.read_text(encoding="utf-8"))
            for path in sorted(_STATIC.glob("*.js"))]


def locale_source() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")


def attachments_css() -> str:
    return claw_static.sheet("attachments.css")


def capabilities_js() -> str:
    return claw_static.sheet("product-capabilities.js")


def static_path(name: str) -> str:
    return str(_STATIC / name)
