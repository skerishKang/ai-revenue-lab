"""Shipped Claw↔Chat continuity sheets for the KILO2 contracts (#8060 45차).

Keeps the raw ``read_text`` calls out of the contract tests: the tests receive
the shipped sources and the parsed locale phrases, with the sheet paths here.
"""
from __future__ import annotations

import locale_bundle

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def app_source() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")


def claw_run_source() -> str:
    return (_STATIC / "chat-claw-run-module.js").read_text(encoding="utf-8")


def claw_form_source() -> str:
    return (_STATIC / "chat-claw-form-module.js").read_text(encoding="utf-8")


def claw_status_source() -> str:
    return (_STATIC / "chat-claw-status-module.js").read_text(encoding="utf-8")


def workspace_css() -> str:
    return (_STATIC / "claw-workspace.css").read_text(encoding="utf-8")


def glass_css() -> str:
    return (_STATIC / "padiem-glass.css").read_text(encoding="utf-8")


def standalone_css() -> str:
    return (_STATIC / "standalone-views.css").read_text(encoding="utf-8")


def calendar_css() -> str:
    return (_STATIC / "calendar.css").read_text(encoding="utf-8")


def library_css() -> str:
    return (_STATIC / "library.css").read_text(encoding="utf-8")


def portrait_css() -> str:
    return (_STATIC / "padiem-glass-portrait.css").read_text(encoding="utf-8")


def panel_layout_css() -> str:
    return (_STATIC / "padiem-glass-panel-layout.css").read_text(encoding="utf-8")


def library_js_source() -> str:
    return (_STATIC / "library.js").read_text(encoding="utf-8")


def locale_source() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")


def locale_phrases(key: str) -> dict[str, str]:
    """One locale key's shipped phrase per language (ko, en)."""
    return {lang: locale_bundle.keys(lang).get(key) for lang in ("ko", "en")}
