"""Shipped-source accessors for UI sheet contracts (#8060).

Raw reads live here. The tests keep every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"


def read(name: str) -> str:
    return (_STATIC / name).read_text(encoding="utf-8")


def index_html() -> str:
    return read("index.html")


def util_manifest_js() -> str:
    return read("util-manifest.js")


def util_app_js() -> str:
    return read("util-app.js")


def util_app_css() -> str:
    return read("util-app.css")


def chat_screen_polish_css() -> str:
    return read("chat-screen-polish.css")


def voice_composer_css() -> str:
    return read("voice-composer.css")


def first_use_css() -> str:
    return read("padiem-first-use.css")


def sidebar_section_polish_css() -> str:
    return read("sidebar-section-polish.css")


def settings_css() -> str:
    return read("padiem-settings.css")


def dark_contrast_css() -> str:
    return read("padiem-dark-contrast.css")


def mode_presentation_css() -> str:
    return read("mode-presentation.css")


def history_css() -> str:
    return read("history.css")


def six_panel_css() -> str:
    return read("shared-six-panel-frame.css")


def tokens_css() -> str:
    return read("padiem-tokens.css")
