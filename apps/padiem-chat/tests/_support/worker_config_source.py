"""#8060 40차: parsed views of the deploy configuration for worker config tests.

wrangler.toml and worker.py are read and parsed here (tomllib for the deploy
config, ast for the worker source), so the contract tests receive parsed
values — never source text inside the test module.
"""
from __future__ import annotations

import ast
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # apps/padiem-chat


def wrangler_text() -> str:
    return (ROOT / "wrangler.toml").read_text(encoding="utf-8")


def worker_text() -> str:
    return (ROOT / "worker.py").read_text(encoding="utf-8")


def wrangler_config() -> dict:
    return tomllib.loads(wrangler_text())


def worker_tree() -> ast.Module:
    return ast.parse(worker_text())


def worker_create_app_kwargs() -> dict[str, str]:
    """Keyword arguments of the worker's ``create_app(...)`` call, unparsed."""
    for node in ast.walk(worker_tree()):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "create_app":
            return {kw.arg: ast.unparse(kw.value) for kw in node.keywords if kw.arg}
    return {}


def worker_assignments() -> dict[str, str]:
    """``name = value`` assignments in the worker, unparsed: top-level names and
    attribute targets (keyed by the attribute's own name)."""
    out: dict[str, str] = {}
    for node in ast.walk(worker_tree()):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                out[target.id] = ast.unparse(node.value)
            elif isinstance(target, ast.Attribute):
                out[target.attr] = ast.unparse(node.value)
    return out


def worker_identifiers() -> set[str]:
    """Every identifier the worker source uses: imported names, names and
    attribute bases — the parsed form of "this text appears in worker.py"."""
    ids: set[str] = set()
    for node in ast.walk(worker_tree()):
        if isinstance(node, ast.Name):
            ids.add(node.id)
        elif isinstance(node, ast.Attribute):
            base = node
            while isinstance(base, ast.Attribute):
                base = base.value
            if isinstance(base, ast.Name):
                ids.add(base.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                ids.add(alias.asname or alias.name.split(".")[0])
    return ids


def worker_string_constants() -> set[str]:
    return {
        node.value for node in ast.walk(worker_tree())
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
