"""Source accessors for R5 module-boundary contracts (#8060).

Raw reads live here. Both nav and Android-handoff module tests keep their
assertions unchanged.
"""
from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"


def app_js() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def nav_module_js() -> str:
    return (_STATIC / "chat-nav-module.js").read_text(encoding="utf-8")


def android_handoff_module_js() -> str:
    return (_STATIC / "chat-android-handoff-module.js").read_text(encoding="utf-8")


def login_dialog_js() -> str:
    return (_STATIC / "chat-login-dialog-module.js").read_text(encoding="utf-8")
