"""Source accessors for the voice mode bounds contract (#8060).

Raw reads live here. The test keeps every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"


def voice_ui_menu_js() -> str:
    return (_STATIC / "voice-ui-menu.js").read_text(encoding="utf-8")


def voice_answer_ui_js() -> str:
    return (_STATIC / "voice-answer-ui.js").read_text(encoding="utf-8")


def voice_call_ui_js() -> str:
    return (_STATIC / "voice-call-ui.js").read_text(encoding="utf-8")
