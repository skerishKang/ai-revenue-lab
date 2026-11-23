"""Source accessors for the MCP and PC delegation settings tests (#8060).

Raw reads live here. Both contract tests keep their assertions and receive
shipped text through these accessors; the harness gets a stable module path.
"""
from __future__ import annotations

from pathlib import Path

from _support import claw_static

_STATIC = Path(__file__).resolve().parents[2] / "static"


def index_html() -> str:
    return claw_static.sheet("index.html")


def locale_js() -> str:
    return claw_static.locale_source()


def mcp_settings_js() -> str:
    return claw_static.sheet("mcp-gateway-settings.js")


def mcp_settings_css() -> str:
    return claw_static.sheet("mcp-gateway-settings.css")


def delegation_js() -> str:
    return claw_static.sheet("pc-delegation-settings.js")


def static_path(name: str) -> Path:
    return _STATIC / name
