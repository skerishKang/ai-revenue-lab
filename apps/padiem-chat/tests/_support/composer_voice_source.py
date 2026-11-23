"""Source accessors for the composer gate and voice auto-send contracts (#8060).

Raw reads live here. The two contract tests keep their assertions and receive
shipped text through these accessors.
"""
from __future__ import annotations

from pathlib import Path

from _support import claw_static

_TESTS = Path(__file__).resolve().parents[1]


def product_capabilities_js() -> str:
    return claw_static.sheet("product-capabilities.js")


def voice_composer_js() -> str:
    return claw_static.sheet("voice-composer.js")


def voice_ui_menu_js() -> str:
    return claw_static.sheet("voice-ui-menu.js")


def voice_browser_journey() -> str:
    return (_TESTS / "browser_voice_live_auto_send_4643.py").read_text(encoding="utf-8")


def voice_browser_journey_path() -> Path:
    return _TESTS / "browser_voice_live_auto_send_4643.py"
