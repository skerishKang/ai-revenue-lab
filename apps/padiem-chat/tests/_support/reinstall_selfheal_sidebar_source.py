"""Shipped-source readers for reinstall/self-heal/sidebar contracts (#8060).

Raw reads live here. The tests keep every assertion unchanged.
"""
from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[4]
_STATIC = _REPO / "apps" / "padiem-chat" / "static"


def read(path, encoding: str = "utf-8") -> str:
    return Path(path).read_text(encoding=encoding)


def install_wrapper() -> str:
    return read(_REPO / "scripts" / "pc_pairing" / "install-padiem-pc.ps1", "utf-8-sig")


def build_script() -> str:
    return read(_REPO / "scripts" / "pc_pairing" / "build-connect-exe.ps1", "utf-8-sig")


def one_click_test_source() -> str:
    return read(_REPO / "apps" / "padiem-chat" / "tests" / "test_5573_pc_one_click_install.py")


def index_html() -> str:
    return (_STATIC / "index.html").read_text(encoding="utf-8")


def app_js() -> str:
    return (_STATIC / "app.js").read_text(encoding="utf-8")
