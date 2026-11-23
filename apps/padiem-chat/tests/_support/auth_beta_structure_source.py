"""Source accessors for the auth-unreachable and beta-UX structure tests (#8060).

Raw reads live here. The two contract tests keep their assertions and receive
shipped text through these accessors.
"""
from __future__ import annotations

from pathlib import Path

from _support import claw_static

_APPS = Path(__file__).resolve().parents[3]
_TESTS = Path(__file__).resolve().parents[1]


def locale_js() -> str:
    return claw_static.locale_source()


def app_js() -> str:
    return claw_static.sheet("app.js")


def login_dialog_js() -> str:
    return claw_static.sheet("chat-login-dialog-module.js")


def council_app_js() -> str:
    return (_APPS / "padiem-council-apps" / "static" / "council-app.js").read_text(encoding="utf-8")


def pc_file_exchange_js() -> str:
    return claw_static.sheet("pc-file-exchange.js")


def pc_file_exchange_css() -> str:
    return claw_static.sheet("pc-file-exchange.css")


def auth_unreachable_node_test() -> Path:
    return _TESTS / "test_5664_auth_unreachable_node.mjs"
