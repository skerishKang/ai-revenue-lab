"""Source accessors for B62 CSS layout contracts (#8060).

Raw reads live here. Both tests keep every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"


def accessibility_polish_css() -> str:
    return (_STATIC / "accessibility-polish.css").read_text(encoding="utf-8")


def sidebar_utility_css() -> str:
    return (_STATIC / "sidebar-utility.css").read_text(encoding="utf-8")


def settings_css() -> str:
    return (_STATIC / "padiem-settings.css").read_text(encoding="utf-8")


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def interaction_polish_js() -> str:
    return (_STATIC / "interaction-polish.js").read_text(encoding="utf-8")


def conversation_motion_js() -> str:
    return (_STATIC / "conversation-motion.js").read_text(encoding="utf-8")


def interaction_polish_css() -> str:
    return (_STATIC / "interaction-polish.css").read_text(encoding="utf-8")


def glass_brand_polish_css() -> str:
    return (_STATIC / "padiem-glass-brand-polish.css").read_text(encoding="utf-8")
