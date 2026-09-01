from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SKIP_PARTS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
}


def _iter_python_files() -> list[Path]:
    files: list[Path] = []
    for path in REPO_ROOT.rglob("*.py"):
        relative = path.relative_to(REPO_ROOT)
        if any(part in SKIP_PARTS for part in relative.parts):
            continue
        files.append(path)
    return sorted(files)


def _record(
    inventory: list[dict[str, object]],
    *,
    path: Path,
    line: int,
    kind: str,
    names: list[str],
) -> None:
    inventory.append(
        {
            "path": path.relative_to(REPO_ROOT).as_posix(),
            "line": line,
            "kind": kind,
            "names": sorted(names),
        }
    )


def collect_package_root_consumers() -> list[dict[str, object]]:
    inventory: list[dict[str, object]] = []

    for path in _iter_python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue

        module_aliases: set[str] = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "padiem_ai_core":
                _record(
                    inventory,
                    path=path,
                    line=node.lineno,
                    kind="from_root",
                    names=[alias.name for alias in node.names],
                )

            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "padiem_ai_core":
                        local_name = alias.asname or "padiem_ai_core"
                        module_aliases.add(local_name)
                        _record(
                            inventory,
                            path=path,
                            line=node.lineno,
                            kind="module_import",
                            names=[local_name],
                        )

            if isinstance(node, ast.Call) and node.args:
                first_arg = node.args[0]
                if not isinstance(first_arg, ast.Constant) or first_arg.value != "padiem_ai_core":
                    continue

                if (
                    isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "importlib"
                    and node.func.attr == "import_module"
                ):
                    _record(
                        inventory,
                        path=path,
                        line=node.lineno,
                        kind="dynamic_module_import",
                        names=["padiem_ai_core"],
                    )
                elif isinstance(node.func, ast.Name) and node.func.id == "__import__":
                    _record(
                        inventory,
                        path=path,
                        line=node.lineno,
                        kind="dynamic_module_import",
                        names=["padiem_ai_core"],
                    )

        if module_aliases:
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id in module_aliases
                ):
                    _record(
                        inventory,
                        path=path,
                        line=node.lineno,
                        kind="root_attribute",
                        names=[node.attr],
                    )

                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "getattr"
                    and len(node.args) >= 2
                    and isinstance(node.args[0], ast.Name)
                    and node.args[0].id in module_aliases
                    and isinstance(node.args[1], ast.Constant)
                    and isinstance(node.args[1].value, str)
                ):
                    _record(
                        inventory,
                        path=path,
                        line=node.lineno,
                        kind="dynamic_root_attribute",
                        names=[node.args[1].value],
                    )

    return sorted(
        inventory,
        key=lambda item: (
            str(item["path"]),
            int(item["line"]),
            str(item["kind"]),
            tuple(item["names"]),
        ),
    )


def test_discover_package_root_consumer_inventory() -> None:
    inventory = collect_package_root_consumers()

    pytest.fail(
        "PACKAGE_ROOT_CONSUMER_INVENTORY\n"
        + json.dumps(inventory, indent=2, ensure_ascii=False)
    )
