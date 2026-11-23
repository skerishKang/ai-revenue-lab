"""Source accessors for the app-entry staging contract (#8060).

Raw shipped-source reads live here. The test keeps every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path

_CHAT = Path(__file__).resolve().parents[2]
_REPO = _CHAT.parents[1]


def council_index_html() -> str:
    return (_REPO / "apps" / "padiem-council-apps" / "static" / "index.html").read_text(encoding="utf-8")


def app_factory_source() -> str:
    return (_CHAT / "app" / "app_factory.py").read_text(encoding="utf-8")


def wrangler_toml() -> str:
    return (_CHAT / "wrangler.toml").read_text(encoding="utf-8")
