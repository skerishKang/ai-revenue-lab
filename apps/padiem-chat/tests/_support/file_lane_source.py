"""File-lane contract accessors for shipped sources (#8060).

Raw reads live here. Tests build harness scripts from the accessor and assert
on parsed worker bindings and sheet statements. The shared ``claw_static``
helper is untouched.
"""
from __future__ import annotations

import ast
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[2]
_STATIC = _APP_ROOT / "static"


def sheet_text(name: str) -> str:
    """One shipped sheet as text; the read stays in this accessor."""
    return (_STATIC / name).read_text(encoding="utf-8")


def sheet_has(name: str, needle: str) -> bool:
    return needle in sheet_text(name)


def worker_env_bindings() -> list[str]:
    """Literal binding names the Worker resolves from ``self.env``."""
    tree = ast.parse((_APP_ROOT / "worker.py").read_text(encoding="utf-8"))
    keys = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        first = node.args[0]
        if not (isinstance(first, ast.Attribute) and first.attr == "env"):
            continue
        for arg in node.args[1:]:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                keys.append(arg.value)
    return keys
