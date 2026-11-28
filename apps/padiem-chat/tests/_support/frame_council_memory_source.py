"""Shipped-source accessors for frame/council/memory contracts (#8060).

Raw reads live here. The tests keep every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path

from _support.app_factory_modules import APP_DIR, FACTORY_MODULES

_TESTS = Path(__file__).resolve().parents[1]
_CHAT = _TESTS.parent
_STATIC = _CHAT / "static"


def glass_gutter_css() -> str:
    return (_STATIC / "padiem-glass-gutter-alignment.css").read_text(encoding="utf8")


def glass_portrait_css() -> str:
    return (_STATIC / "padiem-glass-portrait.css").read_text(encoding="utf8")


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def util_menu_js() -> str:
    return (_STATIC / "util-menu.js").read_text(encoding="utf-8")


def util_menu_css() -> str:
    return (_STATIC / "util-menu.css").read_text(encoding="utf-8")


def util_app_js() -> str:
    return (_STATIC / "util-app.js").read_text(encoding="utf-8")


def app_factory_source() -> str:
    # The original assertions cover both the facade's routes and the migrated
    # owner definitions. Registry-based reads keep those assertions non-vacuous.
    return "\n\n".join(
        (APP_DIR / f"{name}.py").read_text(encoding="utf-8")
        for name in FACTORY_MODULES
    )


def app_js() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")


def council_app_js() -> str:
    return (_CHAT.parent / "padiem-council-apps" / "static" / "council-app.js").read_text(encoding="utf-8")


def chat_app_context_js() -> str:
    return (_STATIC / "chat-app-context.js").read_text(encoding="utf-8")


def memory_module_js() -> str:
    return (_STATIC / "chat-memory-module.js").read_text(encoding="utf-8")


def run_history_module_js() -> str:
    return (_STATIC / "chat-run-history-module.js").read_text(encoding="utf-8")


def strict_deps_js() -> str:
    return (_TESTS / "_r5_strict_deps.js").read_text(encoding="utf-8")


def claw_form_module_js() -> str:
    return (_STATIC / "chat-claw-form-module.js").read_text(encoding="utf-8")


def claw_run_module_js() -> str:
    return (_STATIC / "chat-claw-run-module.js").read_text(encoding="utf-8")
