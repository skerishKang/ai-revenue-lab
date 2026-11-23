"""Source accessors for the help guide page contract (#8060).

Raw reads live here. The test keeps its markup, copy and touch-target checks;
it never reads a shipped file itself.
"""
from __future__ import annotations

from pathlib import Path

import locale_bundle
from _support import claw_static

_STATIC = Path(__file__).resolve().parents[2] / "static"


def help_html() -> str:
    return claw_static.sheet("help.html")


def help_css() -> str:
    return claw_static.sheet("help.css")


def index_html() -> str:
    return claw_static.sheet("index.html")


def install_html() -> str:
    return claw_static.sheet("install.html")


def consent_html() -> str:
    return claw_static.sheet("mcp-oauth-consent.html")


def locale_source() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")


def static_dir() -> str:
    return str(_STATIC)


def tutorial_texts() -> list[str]:
    return [path.read_text(encoding="utf-8")
            for path in sorted((_STATIC / "help-tutorials").glob("*.html"))]


def repo_text(relative: str) -> str:
    return claw_static.repo_source(relative)
