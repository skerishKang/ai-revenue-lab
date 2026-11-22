"""Shipped Connectors-screen sheets for the #5555 contracts (#8060).

Keeps the raw ``read_text`` calls out of the contract tests: the tests receive
the shipped page, module and style sheets, with the sheet paths here.
"""
from __future__ import annotations

import locale_bundle

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def locale_source() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")


def connector_management_js() -> str:
    return (_STATIC / "claw-connector-management.js").read_text(encoding="utf-8")


def home_choices_js() -> str:
    return (_STATIC / "claw-home-choices.js").read_text(encoding="utf-8")


def capability_nav_css() -> str:
    return (_STATIC / "capability-nav.css").read_text(encoding="utf-8")


def connection_state_js() -> str:
    return (_STATIC / "claw-connection-state.js").read_text(encoding="utf-8")


def device_manager_js() -> str:
    return (_STATIC / "claw-device-manager.js").read_text(encoding="utf-8")
