"""Read ownership-mutation handler source for the AST contract tests."""
from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"


def handler_sources(module: str) -> dict[str, str]:
    path = APP / module
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            try:
                out[node.name] = ast.get_source_segment(path.read_text(encoding="utf-8"), node) or ""
            except Exception:
                out[node.name] = ""
    return out
