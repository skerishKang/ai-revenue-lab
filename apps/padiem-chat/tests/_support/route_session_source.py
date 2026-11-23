"""Shipped-source accessors for route/session UI contracts (#8060).

Raw reads live here. The tests keep every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"


def app_js() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")


def nav_js() -> str:
    return (_STATIC / "chat-nav-module.js").read_text(encoding="utf-8")


def conversation_module_js() -> str:
    return (_STATIC / "chat-conversation-module.js").read_text(encoding="utf-8")


def memory_module_js() -> str:
    return (_STATIC / "chat-memory-module.js").read_text(encoding="utf-8")


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def claw_workspace_css() -> str:
    return (_STATIC / "claw-workspace.css").read_text(encoding="utf-8")


def product_capabilities_js() -> str:
    return (_STATIC / "product-capabilities.js").read_text(encoding="utf-8")


def sidebar_utility_css() -> str:
    return (_STATIC / "sidebar-utility.css").read_text(encoding="utf-8")


def login_dialog_js() -> str:
    return (_STATIC / "chat-login-dialog-module.js").read_text(encoding="utf-8")
