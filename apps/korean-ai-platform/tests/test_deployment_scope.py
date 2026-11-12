"""B14 deployment scope: the Worker identity, its watch paths, and the guard.

#7241 3단계: the deployment identity (repository root, watch paths, shared
monorepo packages, contract version) is a deployment value, so this suite
never spells it. Every expectation is read back from the two documents that
declare it — the checked-in scope manifest and the Worker configuration — so
the assertion is still exact, it just has no literal to drift.

The synthetic cases below build their own fixtures and address nothing in the
deployment.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
import re
import tomllib


APP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = APP_ROOT / "deployment_scope.json"
PYPROJECT_PATH = APP_ROOT / "pyproject.toml"
WRANGLER_PATH = APP_ROOT / "wrangler.toml"


def _repository_root() -> str:
    """The application's own path inside the repository, read from the tree."""
    return APP_ROOT.relative_to(REPO_ROOT).as_posix()


def _declared_package_paths(app_root: Path) -> list[str]:
    """Monorepo packages the application itself imports, as repository paths.

    Derived from the application's own import graph and the monorepo layout,
    so the watch-path expectation names no package by hand.
    """
    monorepo_roots = _monorepo_package_roots(REPO_ROOT)
    imported = _source_import_roots(app_root)
    return sorted({path for root, path in monorepo_roots.items() if root in imported})


def _watch_paths(app_root: Path) -> list[str]:
    """One build-watch glob per declared package, plus the application itself."""
    return [f"{_repository_root()}/*"] + [
        f"{path}/*" for path in _declared_package_paths(app_root)
    ]

_SECRET_MARKERS = (
    "api_key=",
    "apikey=",
    "bearer ",
    "password=",
    "secret=",
    "sk-",
    "token=",
)


def _load_manifest() -> dict[str, object]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _project_import_roots(project_root: Path) -> set[str]:
    roots: set[str] = set()
    for base in (project_root / "src", project_root):
        if not base.is_dir():
            continue
        for child in base.iterdir():
            if not child.is_dir() or child.name in {"tests", "docs", ".git", ".venv"}:
                continue
            if (child / "__init__.py").is_file():
                roots.add(child.name)
    return roots


def _monorepo_package_roots(repo_root: Path) -> dict[str, str]:
    packages_root = repo_root / "packages"
    result: dict[str, str] = {}
    if not packages_root.is_dir():
        return result
    for project_root in packages_root.iterdir():
        if not project_root.is_dir():
            continue
        project_rel = project_root.relative_to(repo_root).as_posix()
        for import_root in _project_import_roots(project_root):
            result.setdefault(import_root, project_rel)
    return result


def _absolute_import_roots(source: str, filename: str) -> set[str]:
    tree = ast.parse(source, filename=filename)
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def _source_import_roots(app_root: Path) -> set[str]:
    files = [app_root / "worker.py", *(app_root / "app").rglob("*.py")]
    roots: set[str] = set()
    for path in files:
        roots.update(_absolute_import_roots(path.read_text(encoding="utf-8"), path.as_posix()))
    return roots


def _contains_sys_path_mutation(source: str, filename: str) -> bool:
    tree = ast.parse(source, filename=filename)
    sys_aliases = {"sys"}
    path_aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "sys":
                    sys_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == "sys":
            for alias in node.names:
                if alias.name == "path":
                    path_aliases.add(alias.asname or alias.name)

    def chain(node: ast.AST) -> tuple[str, ...]:
        parts: list[str] = []
        current = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return tuple(reversed(parts))

    for node in ast.walk(tree):
        targets: list[ast.AST] = []
        if isinstance(node, ast.Call):
            targets.append(node.func)
        elif isinstance(node, ast.Assign):
            targets.extend(node.targets)
        elif isinstance(node, ast.AugAssign):
            targets.append(node.target)
        for target in targets:
            parts = chain(target)
            if len(parts) >= 2 and parts[0] in sys_aliases and parts[1] == "path":
                return True
            if parts and parts[0] in path_aliases:
                return True
    return False


def _source_path_escape_files(app_root: Path) -> tuple[str, ...]:
    files = [app_root / "worker.py", *(app_root / "app").rglob("*.py")]
    return tuple(
        path.relative_to(app_root).as_posix()
        for path in files
        if _contains_sys_path_mutation(path.read_text(encoding="utf-8"), path.as_posix())
    )


def _declared_local_dependency_refs(pyproject: dict[str, object]) -> tuple[str, ...]:
    refs: list[str] = []
    project = pyproject.get("project", {})
    if isinstance(project, dict):
        dependencies = project.get("dependencies", [])
        if isinstance(dependencies, list):
            for dependency in dependencies:
                if not isinstance(dependency, str) or "@" not in dependency:
                    continue
                ref = dependency.split("@", 1)[1].strip()
                lower = ref.lower()
                if lower.startswith(("file:", "../", "./", "/")):
                    refs.append(ref)

    tool = pyproject.get("tool", {})
    uv = tool.get("uv", {}) if isinstance(tool, dict) else {}
    sources = uv.get("sources", {}) if isinstance(uv, dict) else {}
    if isinstance(sources, dict):
        for name, config in sources.items():
            if not isinstance(config, dict):
                continue
            path = config.get("path")
            if isinstance(path, str):
                refs.append(path)
            if config.get("workspace") is True:
                refs.append(f"workspace:{name}")
    return tuple(refs)


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _outside_app_local_refs(pyproject: dict[str, object], app_root: Path) -> tuple[str, ...]:
    violations: list[str] = []
    for ref in _declared_local_dependency_refs(pyproject):
        if ref.startswith("workspace:"):
            violations.append(ref)
            continue
        cleaned = re.sub(r"^file:(//)?", "", ref)
        candidate = Path(cleaned)
        resolved = candidate.resolve() if candidate.is_absolute() else (app_root / candidate).resolve()
        if not _is_within(resolved, app_root.resolve()):
            violations.append(ref)
    return tuple(violations)


def _flatten_strings(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, dict):
        return tuple(item for nested in value.values() for item in _flatten_strings(nested))
    if isinstance(value, list):
        return tuple(item for nested in value for item in _flatten_strings(nested))
    return ()


def test_scope_manifest_matches_current_worker_identity_and_is_non_authoritative():
    manifest = _load_manifest()
    wrangler = tomllib.loads(WRANGLER_PATH.read_text(encoding="utf-8"))
    # The contract version identifies the manifest schema the external build
    # automation reads. It is a version string, not a deployment identity: it
    # must be non-empty and versioned rather than restated here.
    version = manifest["contract_version"]
    assert isinstance(version, str) and version.count(".") >= 1 and version.strip() == version
    # The service identity has exactly one authority: the Worker configuration.
    assert manifest["worker_service_name"] == wrangler["name"]
    assert wrangler["name"]
    # The repository root and the Cloudflare root directory are the same place:
    # the application's own directory inside the repository.
    assert manifest["repository_root"] == _repository_root()
    assert manifest["cloudflare_root_directory"] == _repository_root()
    # B14 shares Core's pc_work_metrics, so the Worker build must watch every
    # monorepo package the app imports and the manifest must declare it (the
    # actual Cloudflare Build Watch Paths live outside this repository).
    assert manifest["shared_monorepo_dependency_paths"] == _declared_package_paths(APP_ROOT)
    assert manifest["repository_relative_watch_paths"] == _watch_paths(APP_ROOT)
    assert manifest["watch_path_authority"] == "external_cloudflare_workers_builds"
    assert manifest["repository_guard_only"] is True
    assert manifest["production_deploy_authority"] is False
    assert manifest["security_certification"] is False


def test_manifest_contains_no_secret_like_material():
    for value in _flatten_strings(_load_manifest()):
        lower = value.lower()
        assert not any(marker in lower for marker in _SECRET_MARKERS)


def test_current_b14_has_no_undeclared_monorepo_package_imports():
    manifest = _load_manifest()
    declared = set(manifest["shared_monorepo_dependency_paths"])
    monorepo_roots = _monorepo_package_roots(REPO_ROOT)
    imported_roots = _source_import_roots(APP_ROOT)
    violations = {
        root: path
        for root, path in monorepo_roots.items()
        if root in imported_roots and path not in declared
    }
    assert violations == {}, (
        "B14 imports an undeclared monorepo package; update deployment_scope.json and the external "
        f"Cloudflare Build Watch Paths before accepting the dependency: {violations}"
    )


def test_current_b14_has_no_outside_local_dependency_or_sys_path_escape():
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    assert _outside_app_local_refs(pyproject, APP_ROOT) == ()
    assert _source_path_escape_files(APP_ROOT) == ()


def test_relative_local_dependency_outside_app_fails_closed():
    """A synthetic local reference that climbs out of the app fails closed."""
    package = _declared_package_paths(APP_ROOT)[0]
    escaped = "../" * len(Path(package).parts) + package
    synthetic = {
        "project": {"dependencies": [f"synthetic-local-package @ file:{escaped}"]}
    }
    assert _outside_app_local_refs(synthetic, APP_ROOT) == (f"file:{escaped}",)


def test_uv_workspace_dependency_fails_closed_until_scope_is_declared():
    package = _declared_package_paths(APP_ROOT)[0]
    name = Path(package).name
    synthetic = {
        "tool": {"uv": {"sources": {name: {"workspace": True}}}}
    }
    assert _outside_app_local_refs(synthetic, APP_ROOT) == (f"workspace:{name}",)


def test_sys_path_escape_is_detected_even_with_alias():
    source = "import sys as runtime_sys\nruntime_sys.path.insert(0, '../packages')\n"
    assert _contains_sys_path_mutation(source, "synthetic.py") is True


def test_normal_app_local_imports_do_not_trigger_escape_guard():
    source = "from pathlib import Path\nfrom app.factory import create_worker_app\n"
    assert _contains_sys_path_mutation(source, "synthetic.py") is False
