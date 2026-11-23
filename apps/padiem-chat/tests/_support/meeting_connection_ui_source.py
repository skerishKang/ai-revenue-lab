"""Source accessors for meeting-capture and PC-connection UI contracts (#8060).

Raw reads live here. Both tests keep every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def meeting_capture_js() -> str:
    return (_STATIC / "meeting-capture.js").read_text(encoding="utf-8")


def meeting_capture_css() -> str:
    return (_STATIC / "meeting-capture.css").read_text(encoding="utf-8")


def connection_state_js() -> str:
    return (_STATIC / "claw-connection-state.js").read_text(encoding="utf-8")


def composer_connection_status_js() -> str:
    return (_STATIC / "claw-composer-connection-status.js").read_text(encoding="utf-8")
