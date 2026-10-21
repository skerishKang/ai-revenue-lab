#!/usr/bin/env python3
"""#5341: prove a Core module is outside a product's runtime import closure.

A shared Core module that no product imports cannot change that product's
runtime behavior, so the product's full regression is not a load-bearing
check for it. This module proves that statically and fail-closed:

* a product source file that imports ``padiem_ai_core`` (root or submodule)
  pulls the package ``__init__`` eager surface into the closure, because
  importing any submodule executes the package initialiser;
* Core modules reachable from that closure are dependencies;
* every other Core module is *independent* for that product;
* a text scan of product sources also records ``padiem_ai_core.<module>``
  mentions, so a dynamic ``importlib`` reference can never look independent.

Any unreadable file, parse error, unknown path or oversized change set
returns ``None``. The caller then keeps the safe full-check path.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path


CORE_PACKAGE = "packages/padiem-ai-core/padiem_ai_core"
CORE_TESTS = "packages/padiem-ai-core/tests"
CORE_SOURCE_RE = re.compile(
    r"packages/padiem-ai-core/padiem_ai_core/([a-z][a-z0-9_]*)\.py"
)
CORE_TEST_RE = re.compile(
    r"packages/padiem-ai-core/tests/(test_[A-Za-z0-9_]+\.py)"
)
TEXT_MODULE_RE = re.compile(r"\bpadiem_ai_core\.([a-z][a-z0-9_]*)\b")

MAX_CHANGED_FILES = 100
MAX_FOCUSED_TESTS = 40
MAX_PRODUCT_FILES = 4000

#: Product source trees that consume the shared Core package.
PRODUCT_ROOTS = {
    "b62": ("apps/padiem-chat",),
    "engine": ("apps/padiem-ai-engine",),
}

_SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".tmp",
    ".venv",
    "__pycache__",
    "node_modules",
    "python_modules",
    "venv",
}


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None


def _parse(path: Path) -> ast.AST | None:
    text = _read(path)
    if text is None:
        return None
    try:
        return ast.parse(text)
    except SyntaxError:
        return None


def _product_python_files(root: Path) -> list[Path] | None:
    files: list[Path] = []
    for path in sorted(root.rglob("*.py")):
        try:
            relative = path.relative_to(root)
        except ValueError:  # pragma: no cover - rglob stays inside the root
            return None
        if any(part in _SKIP_DIRS for part in relative.parts):
            continue
        files.append(path)
        if len(files) > MAX_PRODUCT_FILES:
            return None
    return files


def _core_module_files(core_dir: Path) -> dict[str, Path] | None:
    if not core_dir.is_dir():
        return None
    modules: dict[str, Path] = {}
    for path in sorted(core_dir.glob("*.py")):
        if path.stem == "__init__":
            continue
        modules[path.stem] = path
    return modules or None


def _imported_core_names(
    tree: ast.AST, module_names: set[str], relative_is_core: bool = False
) -> tuple[set[str], bool]:
    """Return (direct Core module names, root-package import seen).

    ``relative_is_core`` is true only for files inside the Core package: a
    relative import in a product file points at that product's own package.
    """
    direct: set[str] = set()
    root_import = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                if node.module == "padiem_ai_core":
                    root_import = True
                    for alias in node.names:
                        if alias.name in module_names:
                            direct.add(alias.name)
                elif node.module.startswith("padiem_ai_core."):
                    direct.add(node.module.split(".")[1])
            elif node.level == 1 and relative_is_core:
                # A relative import inside the Core package itself.
                if node.module:
                    direct.add(node.module.split(".")[0])
                else:
                    for alias in node.names:
                        if alias.name in module_names:
                            direct.add(alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "padiem_ai_core":
                    root_import = True
                elif alias.name.startswith("padiem_ai_core."):
                    direct.add(alias.name.split(".")[1])
    return {name for name in direct if name in module_names}, root_import


def _core_edges(
    core_dir: Path, module_files: dict[str, Path]
) -> dict[str, set[str]] | None:
    edges: dict[str, set[str]] = {}
    module_names = set(module_files)
    for name, path in module_files.items():
        tree = _parse(path)
        if tree is None:
            return None
        direct, _ = _imported_core_names(tree, module_names, relative_is_core=True)
        edges[name] = direct
    return edges


def _eager_package_modules(core_dir: Path, module_names: set[str]) -> set[str] | None:
    """Modules the package initialiser imports eagerly.

    Lazy ``importlib.import_module`` surfaces are not listed here: they are
    only executed when a caller asks for the attribute, so they stay
    independent until a product actually imports them.
    """
    tree = _parse(core_dir / "__init__.py")
    if tree is None:
        return None
    eager: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            if node.module:
                eager.add(node.module.split(".")[0])
            else:
                for alias in node.names:
                    eager.add(alias.name)
    return {name for name in eager if name in module_names}


_CLOSURE_CACHE: dict[tuple[str, str], object] = {}
_TEST_MAP_CACHE: dict[str, object] = {}


def _product_closure(
    root: Path, product: str
) -> tuple[set[str], dict[str, set[str]], set[str]] | None:
    """Return (closure, core edges, all core module names) for one product."""
    key = (str(root), product)
    cached = _CLOSURE_CACHE.get(key)
    if cached is not None:
        return cached  # type: ignore[return-value]
    product_roots = PRODUCT_ROOTS.get(product)
    if not product_roots:
        return None
    core_dir = root / CORE_PACKAGE
    module_files = _core_module_files(core_dir)
    if module_files is None:
        return None
    module_names = set(module_files)
    edges = _core_edges(core_dir, module_files)
    if edges is None:
        return None
    eager = _eager_package_modules(core_dir, module_names)
    if eager is None:
        return None

    closure: set[str] = set()
    touches_core = False
    for relative_root in product_roots:
        product_root = root / relative_root
        if not product_root.is_dir():
            return None
        files = _product_python_files(product_root)
        if files is None:
            return None
        for path in files:
            text = _read(path)
            tree = _parse(path)
            if text is None or tree is None:
                return None
            direct, root_import = _imported_core_names(tree, module_names)
            mentioned = set(TEXT_MODULE_RE.findall(text)) & module_names
            if direct or root_import or mentioned:
                touches_core = True
            closure |= direct | mentioned
    if touches_core:
        # Importing any Core submodule executes the package initialiser, so
        # its eager surface is part of every product's closure.
        closure |= eager

    pending = True
    while pending:
        pending = False
        for name in list(closure):
            for dependency in edges.get(name, ()):  # transitive Core imports
                if dependency not in closure:
                    closure.add(dependency)
                    pending = True
    result = (closure, edges, module_names)
    _CLOSURE_CACHE[key] = result
    return result


def _dependent_modules(
    changed: set[str], edges: dict[str, set[str]]
) -> set[str]:
    """Changed modules plus every Core module that imports them."""
    affected = set(changed)
    pending = True
    while pending:
        pending = False
        for name, dependencies in edges.items():
            if name in affected:
                continue
            if dependencies & affected:
                affected.add(name)
                pending = True
    return affected


def _core_test_map(
    core_dir: Path, module_names: set[str]
) -> dict[str, set[str]] | None:
    """Map each Core module to the test modules that exercise it."""
    key = str(core_dir)
    cached = _TEST_MAP_CACHE.get(key)
    if cached is not None:
        return cached  # type: ignore[return-value]
    tests_dir = core_dir.parent / "tests"
    if not tests_dir.is_dir():
        return None
    mapping: dict[str, set[str]] = {name: set() for name in module_names}
    for path in sorted(tests_dir.glob("test_*.py")):
        text = _read(path)
        if text is None:
            return None
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return None
        direct, _ = _imported_core_names(tree, module_names)
        mentioned = set(TEXT_MODULE_RE.findall(text)) & module_names
        for name in direct | mentioned:
            mapping[name].add(path.name)
    _TEST_MAP_CACHE[key] = mapping
    return mapping


def core_focused_plan(
    root: Path, files: object, product: str
) -> dict[str, object] | None:
    """Return the focused plan for a Core-only change set, or ``None``.

    ``None`` means "no proof": the caller must keep the full check path.
    """
    if not isinstance(files, list) or not 0 < len(files) <= MAX_CHANGED_FILES:
        return None
    core_dir = root / CORE_PACKAGE
    if not core_dir.is_dir():
        return None

    source_modules: set[str] = set()
    test_files: set[str] = set()
    seen: set[str] = set()
    for row in files:
        if not isinstance(row, dict) or row.get("status") not in {"added", "modified"}:
            return None
        path = row.get("filename")
        if not isinstance(path, str) or not path:
            return None
        if "\\" in path or ".." in Path(path).parts or path in seen:
            return None
        seen.add(path)
        source = CORE_SOURCE_RE.fullmatch(path)
        test = CORE_TEST_RE.fullmatch(path)
        if source:
            if source.group(1) == "__init__":
                # The package surface itself is shared by every consumer.
                return None
            source_modules.add(source.group(1))
        elif test:
            test_files.add(test.group(1))
        else:
            return None

    if not source_modules and not test_files:
        return None

    closure_result = _product_closure(root, product)
    if closure_result is None:
        return None
    closure, edges, module_names = closure_result
    if not source_modules <= module_names:
        return None
    if source_modules & closure:
        # The changed module is part of the product runtime surface.
        return None

    affected = _dependent_modules(source_modules, edges)
    if affected & closure:
        return None
    if not affected <= module_names:
        return None

    focused_tests: set[str] = set(test_files)
    if affected:
        test_map = _core_test_map(core_dir, module_names)
        if test_map is None:
            return None
        for name in affected:
            focused_tests |= test_map.get(name, set())
            named = f"test_{name}.py"
            if (core_dir.parent / "tests" / named).is_file():
                focused_tests.add(named)
    if len(focused_tests) > MAX_FOCUSED_TESTS:
        return None
    if not focused_tests and not affected:
        return None

    return {
        "independent": True,
        "modules": sorted(affected),
        "tests": sorted(focused_tests),
    }
