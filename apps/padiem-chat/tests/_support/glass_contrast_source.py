"""Shipped-CSS accessors for glass/contrast contracts (#8060).

Raw reads live here. The tests keep every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"


def tokens_css() -> str:
    return (_STATIC / "padiem-tokens.css").read_text(encoding="utf-8")


def rich_response_css() -> str:
    return (_STATIC / "rich-response.css").read_text(encoding="utf-8")


def rich_css() -> str:
    return (_STATIC / "padiem-rich.css").read_text(encoding="utf-8")


def a11y_css() -> str:
    return (_STATIC / "accessibility-polish.css").read_text(encoding="utf-8")


def mobile_legibility_css() -> str:
    return (_STATIC / "mobile-target-legibility.css").read_text(encoding="utf-8")


def themes_css() -> str:
    return (_STATIC / "padiem-themes.css").read_text(encoding="utf-8")


def glass_css() -> str:
    return (_STATIC / "padiem-glass.css").read_text(encoding="utf-8")


def surfaces_css() -> str:
    return (_STATIC / "padiem-surfaces.css").read_text(encoding="utf-8")


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def glass_portrait_css() -> str:
    return (_STATIC / "padiem-glass-portrait.css").read_text(encoding="utf-8")


def glass_gutter_css() -> str:
    return (_STATIC / "padiem-glass-gutter-alignment.css").read_text(encoding="utf-8")


def chat_ui_polish_css() -> str:
    return (_STATIC / "padiem-chat-ui-polish.css").read_text(encoding="utf-8")
