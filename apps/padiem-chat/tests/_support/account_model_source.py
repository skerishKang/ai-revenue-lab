"""Parsed view of the account model-selection route for a privacy contract.

The raw ``read_text`` lives here (#8060 8차) so the contract test asserts on
parsed syntax instead of pinning source spelling.
"""
from __future__ import annotations

import ast
from pathlib import Path


def route_attribute_names() -> set[str]:
    """Every attribute name used by the shipped account-selection route."""

    from app import account_model_selection_routes as routes

    source = Path(routes.__file__).read_text(encoding="utf-8")
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Name):
            names.add(node.id)
    return names
