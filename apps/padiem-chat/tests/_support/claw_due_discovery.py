"""Parsed views for the due-workspace discovery contracts (#8060 39차).

The raw file reads live here; the contract tests receive parsed values
(migration SQL in order, Worker function/import names, Wrangler triggers,
discovery module constants and docstring) and assert on those.
"""
from __future__ import annotations

import ast
import tomllib
from pathlib import Path

from _support.claw_static import migration_source, server_source

_CHAT = Path(__file__).resolve().parents[2]


def due_workspace_migration_sqls() -> tuple[str, str]:
    """The 018/019 migration SQL texts, in apply order."""
    return (
        migration_source("018_claw_automation_durable_store.sql"),
        migration_source("019_claw_automation_rule_provenance.sql"),
    )


def worker_source() -> str:
    return (_CHAT / "worker.py").read_text(encoding="utf-8")


def worker_function_names() -> set[str]:
    tree = ast.parse(worker_source())
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def worker_imported_names() -> set[str]:
    tree = ast.parse(worker_source())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    return names


def wrangler_source() -> str:
    return (_CHAT / "wrangler.toml").read_text(encoding="utf-8")


def wrangler_triggers():
    return tomllib.loads(wrangler_source()).get("triggers")


def discovery_source() -> str:
    return server_source("claw_automation_due_workspace_discovery")


def discovery_constants() -> dict[str, object]:
    tree = ast.parse(discovery_source())
    constants: dict[str, object] = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
        ):
            constants[node.targets[0].id] = node.value.value
    return constants


def discovery_docstring() -> str:
    return ast.get_docstring(ast.parse(discovery_source())) or ""
