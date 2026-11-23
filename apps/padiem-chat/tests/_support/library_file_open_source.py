"""Source accessors for the library file-open contract (#8060).

Raw reads live here. The test keeps its wiring, CSS, migration and Node behavior
contracts; it never reads a shipped file itself.
"""
from __future__ import annotations

from pathlib import Path

from _support import claw_static

_STATIC = Path(__file__).resolve().parents[2] / "static"
_TESTS = Path(__file__).resolve().parents[1]


def library_js() -> str:
    return claw_static.sheet("library.js")


def viewer_js() -> str:
    return claw_static.sheet("library-file-viewer.js")


def index_html() -> str:
    return claw_static.sheet("index.html")


def app_js() -> str:
    return claw_static.sheet("app.js")


def library_css() -> str:
    return claw_static.sheet("library.css")


def harness() -> str:
    return (_TESTS / "_util_library_open_harness.js").read_text(encoding="utf-8")


def migration(name: str) -> str:
    return claw_static.migration_source(name)


def static_path(name: str) -> str:
    return str(_STATIC / name)
