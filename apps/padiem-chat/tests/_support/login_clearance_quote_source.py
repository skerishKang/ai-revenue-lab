"""Shipped-source accessors for login/clearance/quote-access contracts (#8060).

Raw reads live here. The tests keep every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path

import locale_bundle

_STATIC = Path(__file__).resolve().parents[2] / "static"


def read(path, encoding: str = "utf-8") -> str:
    return Path(path).read_text(encoding=encoding)


def locale_source() -> str:
    return locale_bundle.SOURCE.read_text(encoding="utf-8")


def interaction_polish_css() -> str:
    return (_STATIC / "interaction-polish.css").read_text(encoding="utf-8")


def device_manager_js() -> str:
    return (_STATIC / "claw-device-manager.js").read_text(encoding="utf-8")


def workspace_css() -> str:
    return (_STATIC / "claw-workspace.css").read_text(encoding="utf-8")


def quote_runtime_js() -> str:
    return (_STATIC / "b66-quote-runtime.js").read_text(encoding="utf-8")


def quote_runtime_css() -> str:
    return (_STATIC / "b66-quote-runtime.css").read_text(encoding="utf-8")


def tokens_css() -> str:
    return (_STATIC / "padiem-tokens.css").read_text(encoding="utf-8")


def util_menu_css() -> str:
    return (_STATIC / "util-menu.css").read_text(encoding="utf-8")


def pc_file_exchange_css() -> str:
    return (_STATIC / "pc-file-exchange.css").read_text(encoding="utf-8")
