"""Cross-lane test dependency guard.

Represents the OPS/CI guard for issue #3625 (precedent incident: #3593).

Problem
-------
A merge-forward can show ``CHANGED_FILE_OVERLAP=0`` and still break another
workflow. A shared test harness (a component's ``tests/conftest.py``) can grow a
new import, and any *other* workflow that collects that component's test tree
loads the conftest during pytest collection. If the workflow never installed
that dependency the run dies with ``ModuleNotFoundError`` **before a single test
executes**::

    FILE_OVERLAP_ZERO != BEHAVIORAL_DEPENDENCY_ZERO

Guard
-----
For every workflow step that hands pytest an explicit path inside a component
tree (``apps/<c>`` or ``packages/<c>`` that owns a ``pyproject.toml``) this
module statically resolves the *collection-time import closure*:

* every ``conftest.py`` pytest would auto-load for that target, and
* the module-level imports of the collected test modules themselves,

then requires the step's job to either

* run a recognized canonical bootstrap (``uv sync`` / ``uv run`` /
  ``uv pip install``, an editable install of the owning component such as
  ``pip install -e '.[dev]'``, or ``pip install -e <component>``), or
* satisfy the derived closure: the collected tree's first-party import roots are
  importable (on ``PYTHONPATH``, the step's cwd for ``python -m pytest``, or via
  a conftest that self-inserts its own path) **and** its third-party imports are
  installed.

An editable install counts as canonical only when the component's declaration is
pip-resolvable. The uv-only ``file://${PROJECT_ROOT}`` template is not PEP 508,
so ``pip install -e apps/padiem-chat`` cannot succeed; for such a component the
guard falls back to the explicit closure instead of trusting a broken bootstrap.

For ad-hoc jobs (explicit package lists rather than a canonical bootstrap) the
guard also guards declaration drift: a third-party import the collected tree
needs must be installed or declared by the owning component's ``pyproject.toml``
(``UNDECLARED_THIRD_PARTY_TEST_IMPORT``).

Nothing here is a hardcoded ``httpx``/``starlette`` allowlist. Requirements are
derived from the collected tree and the component declaration on every run, so
the guard answers the real question: *can this workflow collect this component's
test tree at all?*

This guards the proven collection-stage coupling class. It does not claim to
detect every possible behavioural coupling, and a canonical bootstrap is trusted
to resolve the component's own declaration (transitive provision by a declared
distribution is not modelled).

Scope: read-only static analysis of ``.github/workflows/*.yml`` plus the
collected test trees. No network, no installs, no product/Production mutation.
"""

from __future__ import annotations

import argparse
import ast
import posixpath
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path

try:  # PyYAML is already a CI dependency of the sibling .github guards.
    import yaml
except ImportError:  # pragma: no cover - reported by main()
    yaml = None  # type: ignore[assignment]


# Distribution name -> import root, for the few packages whose import name
# differs from the distribution name. Used only to *match* an installed
# requirement against an import; never to whitelist a package for a workflow.
DIST_TO_IMPORT_ALIASES = {
    "pyyaml": "yaml",
    "pillow": "PIL",
    "beautifulsoup4": "bs4",
    "python-dateutil": "dateutil",
    "pytest-asyncio": "pytest_asyncio",
    "pytest-cov": "pytest_cov",
    "msgpack-python": "msgpack",
    "opencv-python": "cv2",
    "scikit-learn": "sklearn",
}

COMPONENT_ROOTS = ("apps", "packages")

# Roots pytest itself supplies; they are the test bootstrap, not component deps.
TEST_BOOTSTRAP_ROOTS = frozenset({"pytest", "_pytest"})

# pytest flags that consume the following token as a value.
PYTEST_VALUE_FLAGS = frozenset(
    {
        "-k",
        "-m",
        "-p",
        "-n",
        "-o",
        "-c",
        "-r",
        "-W",
        "-x",
        "--rootdir",
        "--junitxml",
        "--ignore",
        "--deselect",
        "--maxfail",
        "--tb",
        "--import-mode",
        "--confcutdir",
        "--basetemp",
        "--junit-prefix",
        "--capture",
    }
)

# pip/uv install flags that consume the following token as a value.
PIP_VALUE_FLAGS = frozenset(
    {
        "-r",
        "--requirement",
        "-i",
        "--index-url",
        "--extra-index-url",
        "-f",
        "--find-links",
        "-t",
        "--target",
        "--prefix",
        "--src",
        "--platform",
        "--python-version",
        "--constraint",
        "--no-binary",
        "--only-binary",
    }
)

UV_BOOTSTRAP_RE = re.compile(r"(^|[;&|\s])uv\s+(sync|run|pip)\b")
MODULE_PYTEST_RE = re.compile(r"(^|\s)-m\s+pytest(\s|$)")


@dataclass(frozen=True)
class Violation:
    workflow: str
    job: str
    code: str
    detail: str

    def render(self) -> str:
        return f"{self.workflow}::{self.job} {self.code}={self.detail}"


# --------------------------------------------------------------------------- #
# small parsing helpers
# --------------------------------------------------------------------------- #
_STDLIB_FALLBACK = frozenset(
    {
        "__future__",
        "abc",
        "argparse",
        "ast",
        "asyncio",
        "base64",
        "collections",
        "contextlib",
        "csv",
        "dataclasses",
        "datetime",
        "functools",
        "hashlib",
        "http",
        "importlib",
        "inspect",
        "io",
        "itertools",
        "json",
        "math",
        "os",
        "pathlib",
        "re",
        "shlex",
        "shutil",
        "signal",
        "socket",
        "sqlite3",
        "string",
        "struct",
        "subprocess",
        "sys",
        "tempfile",
        "textwrap",
        "threading",
        "time",
        "tokenize",
        "typing",
        "unittest",
        "urllib",
        "uuid",
        "warnings",
        "zipfile",
    }
)


def _stdlib_roots() -> frozenset[str]:
    roots = getattr(sys, "stdlib_module_names", None)
    if roots:
        return frozenset(roots) | {"__future__"}
    return _STDLIB_FALLBACK


def normalize_dist(name: str) -> str:
    name = name.strip().strip("'\"")
    name = name.split(";")[0]
    name = name.split("[")[0]
    name = re.split(r"[<>=!~ ]", name)[0]
    return name.strip().lower().replace("_", "-")


def import_root_for_dist(dist: str) -> str:
    norm = normalize_dist(dist)
    return DIST_TO_IMPORT_ALIASES.get(norm, norm.replace("-", "_"))


def _scripts_of_job(job: dict) -> list[str]:
    scripts: list[str] = []
    for step in job.get("steps") or []:
        run = step.get("run")
        if isinstance(run, str):
            scripts.append(run)
    return scripts


def step_cwd(job: dict, step: dict) -> str:
    step_wd = step.get("working-directory")
    if isinstance(step_wd, str) and step_wd.strip():
        return posixpath.normpath(step_wd.strip())
    default_wd = ((job.get("defaults") or {}).get("run") or {}).get(
        "working-directory"
    )
    if isinstance(default_wd, str) and default_wd.strip():
        return posixpath.normpath(default_wd.strip())
    return "."


def _continuations_joined(script: str) -> list[str]:
    """Split a run script into logical commands, joining backslash breaks."""
    flat = re.sub(r"\\\s*\n", " ", script)
    commands: list[str] = []
    for line in flat.splitlines():
        for part in re.split(r"&&|;|\|\|", line):
            part = part.strip()
            if part:
                commands.append(part)
    return commands


def _tokens(command: str) -> list[str]:
    try:
        return shlex.split(command, posix=True)
    except ValueError:
        return command.split()


def _call_name(func: ast.AST) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        prefix = _call_name(func.value)
        return f"{prefix}.{func.attr}" if prefix else func.attr
    return ""


# --------------------------------------------------------------------------- #
# pytest target discovery
# --------------------------------------------------------------------------- #
def component_of_path(repo: Path, rel: str) -> str | None:
    parts = Path(rel).parts
    if len(parts) >= 2 and parts[0] in COMPONENT_ROOTS:
        comp = Path(parts[0]) / parts[1]
        if (repo / comp / "pyproject.toml").is_file():
            return comp.as_posix()
    return None


def pytest_targets_in_script(repo: Path, script: str, cwd: str) -> list[str]:
    """Return repo-relative component paths that pytest collects in a script."""
    targets: list[str] = []
    for command in _continuations_joined(script):
        tokens = _tokens(command)
        if "pytest" not in tokens:
            continue
        rest = tokens[tokens.index("pytest") + 1 :]
        skip_next = False
        for token in rest:
            if skip_next:
                skip_next = False
                continue
            if token.startswith("-"):
                if token in PYTEST_VALUE_FLAGS:
                    skip_next = True
                continue
            if "/" not in token and not token.endswith(".py"):
                continue
            rel = posixpath.normpath(posixpath.join(cwd, token))
            if component_of_path(repo, rel) is None:
                continue
            if not (repo / rel).exists() and not rel.endswith(".py"):
                continue
            targets.append(rel)
    return targets


# --------------------------------------------------------------------------- #
# collection-time import closure
# --------------------------------------------------------------------------- #
def module_level_import_roots(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return set()
    roots: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue
            if node.module:
                roots.add(node.module.split(".")[0])
    return roots


def _eval_file_path_expr(file_path: Path, node: ast.AST) -> Path | None:
    """Best-effort static evaluation of a ``Path(__file__)``-style expression.

    ``file_path`` is substituted for the ``__file__`` name.
    """
    if isinstance(node, ast.Name) and node.id == "__file__":
        return file_path
    if isinstance(node, ast.Attribute):
        if node.attr == "parent":
            base = _eval_file_path_expr(file_path, node.value)
            return base.parent if base else None
        if node.attr in ("resolve", "absolute"):
            return _eval_file_path_expr(file_path, node.value)
        return None
    if isinstance(node, ast.Subscript):
        base = _eval_file_path_expr(file_path, node.value)
        if base is None:
            return None
        index = node.slice
        if isinstance(index, ast.Constant) and isinstance(index.value, int):
            try:
                return base.parents[index.value]
            except IndexError:
                return None
        return None
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Attribute):
            return _eval_file_path_expr(file_path, node.func.value)
        name = _call_name(node.func)
        if name == "dirname":
            base = next(
                (r for r in (_eval_file_path_expr(file_path, a) for a in node.args) if r),
                None,
            )
            return base.parent if base else None
        if name in {"str", "Path", "os.fspath"}:
            for arg in node.args:
                result = _eval_file_path_expr(file_path, arg)
                if result is not None:
                    return result
            return None
        return None
    return None


def self_bootstrapped_dirs(conftest: Path, repo: Path) -> set[str]:
    """Dirs a conftest adds to ``sys.path`` itself (``sys.path.insert/append``)."""
    conftest = conftest.resolve()
    try:
        tree = ast.parse(conftest.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return set()
    dirs: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr not in ("insert", "append"):
            continue
        target = func.value
        if not (
            isinstance(target, ast.Attribute)
            and target.attr == "path"
            and isinstance(target.value, ast.Name)
            and target.value.id == "sys"
        ):
            continue
        if not node.args:
            continue
        candidate = node.args[-1] if func.attr == "insert" else node.args[0]
        resolved = _eval_file_path_expr(conftest, candidate)
        if resolved is None:
            continue
        try:
            rel = resolved.resolve().relative_to(repo.resolve())
        except (ValueError, OSError):
            continue
        dirs.add(rel.as_posix())
    return dirs


def loaded_conftests(repo: Path, target: Path) -> list[Path]:
    directory = target if target.is_dir() else target.parent
    chain: list[Path] = []
    current = directory.resolve()
    repo = repo.resolve()
    while True:
        conftest = current / "conftest.py"
        if conftest.is_file():
            chain.append(conftest)
        if current == repo:
            break
        parent = current.parent
        if parent == current:
            break
        try:
            parent.relative_to(repo)
        except ValueError:
            break
        current = parent
    return chain


def collected_modules(target: Path) -> list[Path]:
    if target.is_file():
        return [target]
    return sorted(
        p
        for p in target.rglob("*.py")
        if p.name == "conftest.py" or p.name.startswith("test_")
    )


def top_level_roots_in_dir(source_dir: Path) -> set[str]:
    if not source_dir.is_dir():
        return set()
    roots: set[str] = set()
    for child in source_dir.iterdir():
        if child.is_dir() and (child / "__init__.py").is_file():
            roots.add(child.name)
        elif (
            child.is_file()
            and child.suffix == ".py"
            and not child.name.startswith(("setup", "conftest"))
        ):
            roots.add(child.stem)
    return roots


def _component_dirs(repo: Path) -> list[str]:
    dirs: list[str] = []
    for base in COMPONENT_ROOTS:
        base_dir = repo / base
        if not base_dir.is_dir():
            continue
        for child in sorted(base_dir.iterdir()):
            if child.is_dir() and (child / "pyproject.toml").is_file():
                dirs.append(child.relative_to(repo).as_posix())
    return dirs


def _root_providers(repo: Path, root: str) -> list[str]:
    providers: list[str] = []
    for component in _component_dirs(repo):
        candidate = repo / component / root
        if candidate.is_dir() and (candidate / "__init__.py").is_file():
            providers.append(component)
        elif candidate.with_suffix(".py").is_file():
            providers.append(component)
    return providers


def resolve_first_party(repo: Path, component: str, root: str) -> str | None:
    """Resolve a first-party import root for a tree collected from ``component``.

    Deterministic precedence: the owning component itself, then any path
    dependency it declares, then the single unambiguous provider elsewhere in the
    repo. Ambiguity outside the owning component is never guessed.
    """
    own = repo / component / root
    if (own.is_dir() and (own / "__init__.py").is_file()) or own.with_suffix(
        ".py"
    ).is_file():
        return component
    declared_path_roots = path_dep_root_map(repo, component)
    if root in declared_path_roots:
        return declared_path_roots[root]
    providers = [p for p in _root_providers(repo, root) if p != component]
    if len(providers) == 1:
        return providers[0]
    return None


def required_roots(
    repo: Path, target: Path, component: str
) -> tuple[dict[str, str], set[str]]:
    """Return (first_party root -> source parent dir, third_party roots)."""
    files = list(loaded_conftests(repo, target)) + collected_modules(target)
    seen: set[Path] = set()
    stdlib = _stdlib_roots()
    first: dict[str, str] = {}
    third: set[str] = set()
    for module_file in files:
        if module_file in seen:
            continue
        seen.add(module_file)
        for root in module_level_import_roots(module_file):
            if root in stdlib or root in TEST_BOOTSTRAP_ROOTS:
                continue
            source_parent = resolve_first_party(repo, component, root)
            if source_parent is not None:
                first[root] = source_parent
            else:
                third.add(root)
    return first, third


# --------------------------------------------------------------------------- #
# component declaration
# --------------------------------------------------------------------------- #
def _parse_toml(text: str):
    try:
        import tomllib  # Python 3.11+
    except ImportError:  # pragma: no cover
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            return {}
    return tomllib.loads(text)


def read_pyproject_dependencies(
    repo: Path, component: str
) -> tuple[list[str], list[str]]:
    """Return (declared requirements incl. optional extras, uv-only deps)."""
    pyproject = repo / component / "pyproject.toml"
    if not pyproject.is_file():
        return [], []
    try:
        data = _parse_toml(pyproject.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - malformed pyproject is a separate failure
        return [], []
    project = data.get("project") or {}
    declared: list = list(project.get("dependencies") or [])
    for extra in (project.get("optional-dependencies") or {}).values():
        declared.extend(extra or [])
    declared = [str(r) for r in declared]
    uv_only = [req for req in declared if "${PROJECT_ROOT}" in req]
    return declared, uv_only


def _resolve_project_root_path(component: str, req: str) -> str | None:
    match = re.search(r"file://\$\{PROJECT_ROOT\}/(\S+)", req)
    if not match:
        return None
    return posixpath.normpath(posixpath.join(component, match.group(1)))


def path_dep_root_map(repo: Path, component: str) -> dict[str, str]:
    """Map first-party import root -> source dir for a component's path deps."""
    declared, _ = read_pyproject_dependencies(repo, component)
    mapping: dict[str, str] = {}
    for req in declared:
        resolved = _resolve_project_root_path(component, req)
        if resolved is None:
            continue
        for root in top_level_roots_in_dir(repo / resolved):
            mapping.setdefault(root, resolved)
    return mapping


def declared_third_party_roots(repo: Path, component: str) -> set[str]:
    declared, _ = read_pyproject_dependencies(repo, component)
    roots: set[str] = set()
    for req in declared:
        if "${PROJECT_ROOT}" in req:
            continue
        name = normalize_dist(req)
        if not name or "/" in name:
            continue
        roots.add(import_root_for_dist(name))
    return roots


def declared_path_dep_roots(repo: Path, component: str) -> set[str]:
    return set(path_dep_root_map(repo, component))


# --------------------------------------------------------------------------- #
# job environment
# --------------------------------------------------------------------------- #
def job_pythonpath_dirs(job: dict, step: dict) -> set[str]:
    raw_entries: list[str] = []
    for source in (job.get("env") or {}, step.get("env") or {}):
        if isinstance(source, dict) and source.get("PYTHONPATH"):
            raw_entries.append(str(source["PYTHONPATH"]))
    cwd = step_cwd(job, step)
    dirs: set[str] = set()
    for raw in raw_entries:
        used_placeholder = bool(
            re.search(r"\$\{\{\s*github\.workspace\s*\}\}", raw)
        ) or "${workspace}" in raw or "$GITHUB_WORKSPACE" in raw
        cleaned = re.sub(r"\$\{\{\s*github\.workspace\s*\}\}", "", raw)
        cleaned = cleaned.replace("${workspace}", "").replace("$GITHUB_WORKSPACE", "")
        for part in cleaned.split(":"):
            part = part.strip().strip("'\"")
            if not part:
                continue
            if part.startswith("/"):
                # ``${{ github.workspace }}/apps/x`` leaves a leading slash once
                # the placeholder is removed; re-anchor it to the repo root.
                if not used_placeholder:
                    continue
                part = part.lstrip("/")
            dirs.add(posixpath.normpath(posixpath.join(cwd, part)))
    return dirs


def _resolve_editable_target(cwd: str, target: str) -> str:
    cleaned = target.strip().strip("'\"").split("[")[0]
    if cleaned.startswith("/"):
        return posixpath.normpath(cleaned)
    return posixpath.normpath(posixpath.join(cwd, cleaned))


def job_install_info(job: dict) -> tuple[set[str], set[str]]:
    """Return (installed distribution names, editable source dirs)."""
    names: set[str] = set()
    editables: set[str] = set()
    for step in job.get("steps") or []:
        run = step.get("run")
        if not isinstance(run, str):
            continue
        cwd = step_cwd(job, step)
        for command in _continuations_joined(run):
            tokens = _tokens(command)
            if "install" not in tokens:
                continue
            if "pip" not in tokens and not UV_BOOTSTRAP_RE.search(command):
                continue
            rest = tokens[tokens.index("install") + 1 :]
            position = 0
            while position < len(rest):
                token = rest[position]
                if token in ("-e", "--editable"):
                    if position + 1 < len(rest):
                        editables.add(
                            _resolve_editable_target(cwd, rest[position + 1])
                        )
                    position += 2
                    continue
                if token in PIP_VALUE_FLAGS:
                    position += 2
                    continue
                if token.startswith("-"):
                    position += 1
                    continue
                if "://" in token or token.endswith(".txt") or "/" in token:
                    position += 1
                    continue
                names.add(normalize_dist(token))
                position += 1
    return names, editables


def recognizes_uv_bootstrap(job: dict) -> bool:
    return any(UV_BOOTSTRAP_RE.search(script) for script in _scripts_of_job(job))


def recognizes_editable_component(job: dict, component: str) -> set[str]:
    """Editable installs whose source dir covers ``component``."""
    _, editables = job_install_info(job)
    covered: set[str] = set()
    for editable in editables:
        if editable == component or component.startswith(editable + "/"):
            covered.add(editable)
    return covered


def implicit_cwd_dirs(job: dict, step: dict) -> set[str]:
    """The step cwd is importable for ``python -m pytest`` / ``uv run python -m``."""
    run = step.get("run")
    if not isinstance(run, str) or not MODULE_PYTEST_RE.search(run):
        return set()
    return {step_cwd(job, step)}


# --------------------------------------------------------------------------- #
# evaluation
# --------------------------------------------------------------------------- #
def evaluate(repo: Path) -> tuple[list[Violation], dict[str, int]]:
    if yaml is None:
        raise RuntimeError("PyYAML is required to evaluate workflows")
    violations: list[Violation] = []
    stats = {
        "workflows_scanned": 0,
        "component_collections": 0,
        "conftest_couplings": 0,
    }
    workflows_dir = repo / ".github" / "workflows"

    for workflow_path in sorted(workflows_dir.glob("*.yml")):
        data = yaml.safe_load(workflow_path.read_text(encoding="utf-8")) or {}
        stats["workflows_scanned"] += 1
        workflow_name = workflow_path.name
        for job_name, job in (data.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            for step in job.get("steps") or []:
                run = step.get("run")
                if not isinstance(run, str):
                    continue
                cwd = step_cwd(job, step)
                for rel in pytest_targets_in_script(repo, run, cwd):
                    component = component_of_path(repo, rel)
                    if component is None:
                        continue
                    stats["component_collections"] += 1
                    target = repo / rel
                    conftests = loaded_conftests(repo, target)
                    if conftests:
                        stats["conftest_couplings"] += 1
                    first, third = required_roots(repo, target, component)

                    _, uv_only = read_pyproject_dependencies(repo, component)
                    declared_roots = declared_third_party_roots(repo, component)
                    declared_roots |= declared_path_dep_roots(repo, component)
                    provided, _ = job_install_info(job)
                    provided_roots = {import_root_for_dist(n) for n in provided}

                    canonical = recognizes_uv_bootstrap(job)
                    if not canonical and recognizes_editable_component(job, component):
                        # Canonical only when the declaration is pip-resolvable.
                        # The uv-only file://${PROJECT_ROOT} template is not, so
                        # ``pip install -e <component>`` cannot succeed for it.
                        canonical = not uv_only

                    if canonical:
                        provided_roots |= declared_roots
                        provided_roots |= top_level_roots_in_dir(repo / component)
                        provided_roots |= declared_path_dep_roots(repo, component)

                    if not canonical:
                        importable_dirs = job_pythonpath_dirs(job, step)
                        importable_dirs |= implicit_cwd_dirs(job, step)
                        for conftest in conftests:
                            importable_dirs |= self_bootstrapped_dirs(conftest, repo)
                        for root, parent in sorted(first.items()):
                            if parent not in importable_dirs and root not in provided_roots:
                                violations.append(
                                    Violation(
                                        workflow_name,
                                        job_name,
                                        "MISSING_FIRST_PARTY_ROOT",
                                        f"{root} (expected {parent} importable)",
                                    )
                                )
                        for root in sorted(third):
                            if root not in provided_roots:
                                violations.append(
                                    Violation(
                                        workflow_name,
                                        job_name,
                                        "MISSING_THIRD_PARTY_DEP",
                                        f"{root} (collected tree imports it; install a provider)",
                                    )
                                )

                        # Ad-hoc jobs only: the explicit install list must not
                        # silently diverge from the component's own declaration.
                        for root in sorted(third):
                            if root not in provided_roots and root not in declared_roots:
                                violations.append(
                                    Violation(
                                        workflow_name,
                                        job_name,
                                        "UNDECLARED_THIRD_PARTY_TEST_IMPORT",
                                        f"{root} (not declared by {component}/pyproject.toml)",
                                    )
                                )
    return violations, stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cross-lane test dependency guard")
    parser.add_argument("--repo", default=".", help="repository root")
    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve()

    if yaml is None:
        print("CROSS_LANE_DEPENDENCY_GUARD=ERROR")
        print("GUARD_REASON=PyYAML_NOT_INSTALLED")
        return 2

    violations, stats = evaluate(repo)
    print(f"CROSS_LANE_WORKFLOWS_SCANNED={stats['workflows_scanned']}")
    print(f"CROSS_LANE_COMPONENT_COLLECTIONS={stats['component_collections']}")
    print(f"CROSS_LANE_CONFTEST_COUPLINGS={stats['conftest_couplings']}")
    print(
        "SHARED_TEST_HARNESS_COUPLING_DETECTED="
        + ("YES" if stats["conftest_couplings"] > 0 else "NO")
    )
    print("AD_HOC_DEPENDENCY_DRIFT_GUARDED=YES")

    if violations:
        print("CROSS_LANE_DEPENDENCY_GUARD=FAIL")
        for violation in violations:
            print(f"CROSS_LANE_VIOLATION {violation.render()}")
        return 1

    print("CROSS_LANE_DEPENDENCY_GUARD=PASS")
    print("PRODUCT_SOURCE_CHANGE=NO")
    print("MODEL_PROVIDER_CHANGE=NO")
    print("PRODUCTION_MUTATION=0")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
