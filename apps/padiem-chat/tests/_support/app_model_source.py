"""Shipped-source accessors for app/model contracts (#8060).

Raw reads live here. The tests keep every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path

_TESTS = Path(__file__).resolve().parents[1]
_STATIC = _TESTS.parent / "static"
_REPO = _TESTS.parent.parent.parent


def read(path) -> str:
    return Path(path).read_text(encoding="utf-8")


def frame_css() -> str:
    return (_STATIC / "shared-six-panel-frame.css").read_text(encoding="utf-8")


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def app_js() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")


def usage_log_js() -> str:
    return (_STATIC / "chat-usage-log-module.js").read_text(encoding="utf-8")


def feedback_css() -> str:
    return (_STATIC / "chat-feedback.css").read_text(encoding="utf-8")


def feedback_js() -> str:
    return (_STATIC / "chat-feedback-module.js").read_text(encoding="utf-8")


def claw_status_js() -> str:
    return (_STATIC / "chat-claw-status-module.js").read_text(encoding="utf-8")


def council_app_js() -> str:
    return (_REPO / "apps" / "padiem-council-apps" / "static" / "council-app.js").read_text(encoding="utf-8")


def locale_js() -> str:
    import locale_bundle

    return locale_bundle.SOURCE.read_text(encoding="utf-8")
