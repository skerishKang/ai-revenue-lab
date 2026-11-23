"""Source accessors for the private-RPC parity and R5 core-module tests (#8060).

Raw reads live here. Both contract tests keep their assertions and receive
shipped text or parsed modules through these accessors.
"""
from __future__ import annotations

import ast
from pathlib import Path

from _support import claw_static

_STATIC = Path(__file__).resolve().parents[2] / "static"


def module_ast(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def source_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def app_js() -> str:
    return claw_static.sheet("app.js")


def core_module_js() -> str:
    return claw_static.sheet("chat-core-module.js")


def index_html() -> str:
    return claw_static.sheet("index.html")


def static_dir() -> str:
    return str(_STATIC)
