"""#8060: raw reads for the profile menu contracts.

index.html, app.js, chat-profile-menu-module.js, sidebar-utility.css,
padiem-tokens.css, padiem-themes.css, padiem-cinematic-workspace.css and
chat-connectors-module.js are read here, so the contract tests receive the
shipped sources without opening static files themselves.
"""
from __future__ import annotations

from pathlib import Path

from _support.claw_static import sheet

ROOT = Path(__file__).resolve().parents[2]

HTML = sheet("index.html")
APP = sheet("app.js")
MODULE = sheet("chat-profile-menu-module.js")
CSS = sheet("sidebar-utility.css")
TOKENS = sheet("padiem-tokens.css")
THEMES = sheet("padiem-themes.css")
CINEMATIC = sheet("padiem-cinematic-workspace.css")
CONNECTORS = sheet("chat-connectors-module.js")


def bottom_section() -> str:
    """The sidebar bottom tools + account markup from index.html."""
    html = HTML
    tools = html.split('class="sidebar-bottom-tools"', 1)[1].split('class="sidebar-bottom"', 1)[0]
    pinned = html.split('class="sidebar-bottom"', 1)[1].split("</aside>", 1)[0]
    return tools + pinned
