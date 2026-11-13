#!/usr/bin/env python3
"""Fail-closed B62 change-impact classification for CI lanes.

Exact static-only edits select static JavaScript parse and DOM/origin/privacy
audits, with separate path-scoped browser QA; unchanged Python/Worker/Core
regression and vendoring jobs are skipped. Chat tests-tree edits -- test
modules, helpers those tests import, and plain docs -- run exactly the affected
modules; a helper nothing imports or conftest.py falls back to the full suite.
B14-only edits retain Chat pytest and Worker packaging but skip unchanged real
Worker boots; source/runtime changes retain their full applicable gates.
Unknown event/API/changes => full.
"""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import re
import sys
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ci_core_import_scope import core_focused_plan  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]

MAX_FILES = 100
FULL = "full"
CHAT_ONLY = "chat_only"
STATIC_ONLY = "static_only"
UI_MIXED = "ui_mixed"
TESTS_ONLY = "tests_only"
B14_ONLY = "b14_only"
B14_TESTS_ONLY = "b14_tests_only"
CORE_FOCUSED_ONLY = "core_focused_only"
B14_ATTEMPT_ONLY = "b14_attempt_only"

# #4459: source-invariant static UI and changed pytest modules. Run every
# changed test in the UI-mixed job; no deploy/auth/Worker/CI script ever qualifies.
UI_MIXED_MAX_FILES = 25
UI_CONTRACT_MAX_MODULES = 400
_UI_MIXED_STATIC = re.compile(
    r"apps/padiem-chat/static/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\.(?:css|html|js)"
)
_UI_MIXED_TEST = re.compile(r"apps/padiem-chat/tests/test_[A-Za-z0-9_]+\.py")
# #7186: a flat member of Chat's tests tree: a test module, an imported helper
# or plain documentation. A helper is not runnable on its own, so the changed
# set is covered by the flat tests that import it. A doc's filename carries no
# import contract, so it does not have to be an ASCII identifier.
_TESTS_TREE_PY = re.compile(r"apps/padiem-chat/tests/[A-Za-z0-9_]+\.py")
_TESTS_TREE_DOC = re.compile(r"apps/padiem-chat/tests/[^/\\]+\.md")
_TESTS_TREE_CONFTEST = "apps/padiem-chat/tests/conftest.py"


def _is_static_segment(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str) \
        and node.value.strip().strip("/\\") == "static"


def _references_static_source(tree: ast.AST) -> bool:
    """True when a test module reads a path that includes the static root.

    Detects the three shapes the repository actually uses:
    ``ROOT / "static" / "app.js"``, ``Path("static")`` / ``os.path.join(..., "static", ...)``,
    and literal paths such as ``"static/index.html"`` or ``.../static/app.js``.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            if _is_static_segment(node.left) or _is_static_segment(node.right):
                return True
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else (
                func.id if isinstance(func, ast.Name) else "")
            if name in {"join", "Path", "PurePath"} and any(
                    _is_static_segment(argument) for argument in node.args):
                return True
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
            if (value.startswith(("static/", "static\\"))
                    or "/static/" in value or "\\static\\" in value):
                return True
    return False


def _static_reading_helpers(tests_dir: Path) -> tuple[str, ...]:
    """Non-test files under tests/ whose own source reads a path under static/.

    A pytest module can read a shipped static file THROUGH one of these
    helpers (a node harness .cjs/.mjs/.js or a shared source reader such as
    ``_r5_function_source.py``) without ever naming "static" itself. #7433:
    a static-only PR changed chat-transport.js / claw-device-manager.js, the
    classifier saw no direct reader for the two harness tests, and both
    merged broken to main. The helper list closes that indirection.
    """
    helpers: list[str] = []
    try:
        candidates = sorted(tests_dir.iterdir())
    except OSError:
        return ()
    for path in candidates:
        if not path.is_file():
            continue
        if path.suffix == ".py" and path.name.startswith("test_"):
            continue
        if path.suffix not in {".py", ".js", ".cjs", ".mjs"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        if ("static/" in text or "static\\" in text
                or '"static"' in text or "'static'" in text):
            helpers.append(path.name)
    return tuple(helpers)


def _mentions_static_reading_helper(source: str, helpers: tuple[str, ...]) -> bool:
    return any(
        helper in source or helper.rsplit(".", 1)[0] in source
        for helper in helpers
    )


def ui_contract_tests(repo_root: Path | None = None) -> tuple[str, ...]:
    """Every B62 pytest module whose source reads a path under static/,
    directly or through a static-reading helper under tests/.

    The list is derived from the sources, so a new UI-contract module is
    covered without editing this classifier. A module that cannot be parsed is
    left out; an empty result for a static change fails closed in main().
    """
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    tests_dir = root / "apps/padiem-chat/tests"
    try:
        candidates = sorted(tests_dir.glob("test_*.py"))
    except OSError:
        return ()
    helpers = _static_reading_helpers(tests_dir)
    modules: list[str] = []
    for path in candidates:
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        if _references_static_source(tree) or _mentions_static_reading_helper(source, helpers):
            modules.append(f"tests/{path.name}")
    # #7599: deployed parity audit is a load-bearing UI contract that verifies
    # deployed assets against static sources; ensure it is always in the UI contract list.
    parity_test = "tests/test_deployed_parity_audit.py"
    if (tests_dir / "test_deployed_parity_audit.py").is_file() and parity_test not in modules:
        modules.append(parity_test)
        modules.sort()
    if len(modules) > UI_CONTRACT_MAX_MODULES:
        return ()
    return tuple(modules)


def _has_static_change(files: object) -> bool:
    return isinstance(files, list) and any(
        isinstance(row, dict) and isinstance(row.get("filename"), str)
        and row["filename"].startswith("apps/padiem-chat/static/")
        for row in files
    )


def chat_source_changed(files: object) -> bool:
    """True when a change touches the shipped Chat Python surface.

    #6801: chat_only PRs used to run no Chat pytest module at all. The full
    suite is the load-bearing lane for these changes. A malformed/ambiguous
    file listing returns True at the caller so the lane fails closed.
    """
    if not isinstance(files, list):
        return False
    for row in files:
        if not isinstance(row, dict):
            continue
        path = row.get("filename")
        if not isinstance(path, str):
            continue
        # Withdrawal tests derive the reviewed product boundary from this
        # authority source; a boundary change must exercise those consumers.
        if path in {"apps/padiem-chat/worker.py", "packages/padiem-control-plane/identity_authority_worker.py"} or (
            path.startswith("apps/padiem-chat/app/") and path.endswith(".py")
        ):
            return True
    return False


def ui_mixed_test_modules(files: object) -> tuple[str, ...]:
    """Safe relative pytest arguments, only for strictly proven static+tests."""
    if not isinstance(files,list) or not 2 <= len(files) <= UI_MIXED_MAX_FILES:
        return ()
    static_count = 0
    modules: list[str] = []
    seen: set[str] = set()
    for row in files:
        if not isinstance(row,dict) or row.get("status") not in {"added","modified"}:
            return ()
        path = row.get("filename")
        if not isinstance(path,str) or path in seen or "\\" in path or ".." in Path(path).parts:
            return ()
        seen.add(path)
        if _UI_MIXED_STATIC.fullmatch(path):
            static_count += 1
        elif _UI_MIXED_TEST.fullmatch(path):
            modules.append(path.removeprefix("apps/padiem-chat/"))
        else:
            return ()
    return tuple(sorted(modules)) if static_count and modules else ()


def _is_tests_tree_file(path: str) -> bool:
    """A flat file directly under Chat's tests tree (helpers and docs included)."""
    return bool(_TESTS_TREE_PY.fullmatch(path) or _TESTS_TREE_DOC.fullmatch(path))


def _is_tests_tree_path(path: str) -> bool:
    """A flat file directly under Chat's tests tree that a narrow lane can cover.

    ``conftest.py`` is loaded by pytest around every module in the directory, so
    no reduced module list covers its effect; it stays on the full path.
    """
    return _is_tests_tree_file(path) and path != _TESTS_TREE_CONFTEST


def _is_tests_tree_change(files: object) -> bool:
    """True when every changed path is a flat Chat tests-tree file.

    Shape only, mirroring the ``impact_scope`` tests-tree branch, so main() can
    settle the lane and the runner together. Whether a runnable module set
    exists is ``tests_only_modules``.
    """
    if not isinstance(files, list) or not 0 < len(files) <= MAX_FILES:
        return False
    paths: list[str] = []
    for row in files:
        if not isinstance(row, dict) or row.get("status") not in {"added", "modified"}:
            return False
        path = row.get("filename")
        if not isinstance(path, str) or "\\" in path or ".." in Path(path).parts:
            return False
        if not _is_tests_tree_file(path):
            return False
        paths.append(path)
    return any(path.endswith(".py") for path in paths)


def _imported_module_names(tree: ast.AST) -> frozenset[str]:
    """Module names a test reads: static imports plus literal dynamic imports.

    The dynamic forms are the ones the repository uses; a caller built from a
    computed string cannot be proven and is not claimed here.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            func = node.func
            target = func.attr if isinstance(func, ast.Attribute) else (
                func.id if isinstance(func, ast.Name) else "")
            if target in {"import_module", "__import__"} and node.args:
                argument = node.args[0]
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    names.add(argument.value.split(".")[0])
    return frozenset(names)


def test_module_importers(module_name: str, repo_root: Path | None = None) -> tuple[str, ...]:
    """Flat ``tests/test_*.py`` modules that import ``module_name`` directly.

    Transitive importers are deliberately not followed: an unchanged helper
    between the change and the tests means the module list is not proven, and
    the caller keeps the full Chat suite instead of guessing.
    """
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    tests_dir = root / "apps/padiem-chat/tests"
    try:
        candidates = sorted(tests_dir.glob("test_*.py"))
    except OSError:
        return ()
    importers: list[str] = []
    for path in candidates:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, ValueError):
            continue
        if module_name in _imported_module_names(tree):
            if not re.fullmatch(r"test_[A-Za-z0-9_]+\.py", path.name):
                # The reduced lane only accepts this exact module shape; never
                # silently drop a consumer it cannot name.
                return ()
            importers.append(f"tests/{path.name}")
    return tuple(importers)


def tests_only_modules(files: object, repo_root: Path | None = None) -> tuple[str, ...]:
    """Safe relative pytest arguments for a Chat tests-tree-only change.

    A changed ``test_*.py`` runs itself. A changed helper runs every flat test
    module that imports it. A helper no test imports (or conftest.py) cannot be
    covered by a reduced lane, so the result is empty and the caller fails
    closed to the full Chat suite. ``.md`` files carry no executable contract
    and are ignored. The shape is re-proven here so a malformed API listing can
    never turn into a silently wrong pytest invocation.
    """
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
        return ()
    modules: set[str] = set()
    helpers: set[str] = set()
    seen: set[str] = set()
    for row in files:
        if not isinstance(row, dict) or row.get("status") not in {"added", "modified"}:
            return ()
        path = row.get("filename")
        if not isinstance(path, str) or path in seen or "\\" in path or ".." in Path(path).parts:
            return ()
        if not _is_tests_tree_path(path):
            return ()
        seen.add(path)
        if path.endswith(".md"):
            continue
        name = path.rsplit("/", 1)[-1]
        if name.startswith("test_"):
            modules.add(f"tests/{name}")
        else:
            helpers.add(name[: -len(".py")])
    for helper in sorted(helpers):
        importers = test_module_importers(helper, repo_root)
        if not importers:
            return ()
        modules.update(importers)
        if len(modules) > MAX_FILES:
            return ()
    return tuple(sorted(modules))


def impact_scope(files: object, repo_root: Path | None = None) -> str:
    if not isinstance(files, list) or not 0 < len(files) <= MAX_FILES:
        return FULL
    paths = []
    for row in files:
        if not isinstance(row, dict) or row.get("status") not in {"added", "modified"}:
            return FULL
        path = row.get("filename")
        if not isinstance(path, str) or not (
            path.startswith("apps/padiem-chat/")
            or path.startswith("apps/korean-ai-platform/")
            or path.startswith("packages/padiem-ai-core/")
        ):
            return FULL
        # Do not accept malformed paths, explicit traversal or duplicates.
        if not path or "\\" in path or ".." in Path(path).parts or path in paths:
            return FULL
        paths.append(path)
    b14_attempt_paths = {
        "apps/padiem-chat/app/b14_client.py",
        "apps/padiem-chat/tests/test_3977_provider_default_temperature_bridge.py",
        "apps/padiem-chat/tests/test_owner_tier_fallback_dispatch_261015.py",
        "apps/padiem-chat/tests/test_attachments.py",
        "apps/padiem-chat/tests/test_dispatch_quota_refund.py",
        "apps/padiem-chat/tests/test_documents.py",
        "apps/padiem-chat/tests/test_grounding.py",
        "apps/padiem-chat/tests/test_service_binding.py",
        "apps/padiem-chat/tests/test_skills.py",
    }
    if "apps/padiem-chat/app/b14_client.py" in paths and set(paths) <= b14_attempt_paths:
        return B14_ATTEMPT_ONLY
    # #5341: a shared Core change that no product imports cannot change that
    # product's runtime. The static import-scope proof decides it; anything the
    # proof cannot establish stays on the full path.
    core_paths = [p for p in paths if p.startswith("packages/padiem-ai-core/")]
    if core_paths:
        if len(core_paths) != len(paths):
            return FULL
        plan = core_focused_plan(repo_root or REPO_ROOT, files, "b62")
        return CORE_FOCUSED_ONLY if plan else FULL
    # B14 unit-test-only changes never alter either product's shipped sources,
    # pinned dependencies or runtime probes. B14's independent validate-b14-alpha
    # workflow runs the *complete* B14 test suite on every such PR and main push.
    # Keep the B14 pilot contract check here and the stable b62-test check context,
    # but omit unchanged B62 host/Worker jobs only for this exact narrow case.
    if all(re.fullmatch(r"apps/korean-ai-platform/tests/test_[^/]+\.py", p) for p in paths):
        return B14_TESTS_ONLY

    # B14 pilot source/tests are a separate deployed application: they cannot
    # change B62 Worker/Pyodide probe entrypoints, pinned vendor locks or
    # B62 Core source. Keep full B62 Chat integration + B14 tests + bundle,
    # but do not launch four source-identical B62 local Workerd runtimes.
    # Deliberately EXCLUDE B14 pyproject/locks/scripts and mixed changes.
    if all(
        re.fullmatch(r"apps/korean-ai-platform/app/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\.(?:py|json)", p)
        or re.fullmatch(r"apps/korean-ai-platform/tests/test_[^/]+\.py", p)
        for p in paths
    ):
        return B14_ONLY
    if all(p.startswith("apps/padiem-chat/static/") for p in paths):
        return STATIC_ONLY
    if ui_mixed_test_modules(files):
        return UI_MIXED
    # #3989/#7186: a Chat tests-tree-only change cannot alter the bundled
    # Worker code or its locked Pyodide dependencies. Run exactly the affected
    # test modules -- changed test modules, plus the tests that import a
    # changed helper. A helper with no importing test, and conftest.py, prove
    # no reduced set; they must not drift into CHAT_ONLY, which runs no pytest
    # either, so the answer is the fail-closed full path.
    if any(path.endswith(".py") for path in paths) and all(
        _is_tests_tree_file(path) for path in paths
    ):
        return TESTS_ONLY if tests_only_modules(files, repo_root) else FULL
    # A B62-only dependency/Worker configuration change can alter the Core
    # execution environment without editing Core sources. Never fast-route it.
    source_roots = ("apps/padiem-chat/app/", "apps/padiem-chat/tests/")
    if all(
        p.startswith("apps/padiem-chat/static/")
        or (p.startswith(source_roots) and p.endswith(".py"))
        or p == "apps/padiem-chat/worker.py"
        for p in paths
    ):
        return CHAT_ONLY
    return FULL


def changed_files(event: dict, event_name: str, repository: str, token: str):
    if not token or not re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
        return None
    if not isinstance(event, dict) or event.get("repository", {}).get("full_name") != repository:
        return None
    if event_name == "pull_request":
        pr = event.get("pull_request") or {}
        base = (pr.get("base") or {}).get("sha")
        head = (pr.get("head") or {}).get("sha")
    elif event_name == "push":
        base, head = event.get("before"), event.get("after")
    else:
        return None
    if not all(isinstance(s, str) and re.fullmatch("[0-9a-f]{40}", s) and set(s) != {"0"} for s in (base, head)):
        return None

    url = f"https://api.github.com/repos/{repository}/compare/{base}...{head}"
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "padiem-b62-ci-impact/1.0",
    })
    with urllib.request.urlopen(request, timeout=15) as response:
        result = json.load(response)
    if not isinstance(result, dict):
        return None
    status = result.get("status")
    if status not in {"ahead", "identical", "diverged"}:
        return None
    files = result.get("files")
    if not isinstance(files, list) or len(files) > MAX_FILES:
        return None
    # A PR branch can legitimately be behind main: GitHub compare returns
    # 'diverged' even when its merge-base..head diff touches only one CSS file.
    # Accept this PR-only case only with an exact changed-file count, so
    # truncated/uncertain API responses never turn into a reduced CI lane.
    if status == "diverged":
        if event_name != "pull_request":
            return None
        count = pr.get("changed_files")
        ahead = result.get("ahead_by")
        if (type(count) is not int or not 0 < count <= MAX_FILES
                or type(ahead) is not int or ahead < 1
                or len(files) != count):
            return None
    elif event_name == "pull_request":
        count = pr.get("changed_files")
        if type(count) is int and count != len(files):
            return None
    return files


def _load_event_files() -> tuple[dict, str, object | None]:
    with Path(os.environ["GITHUB_EVENT_PATH"]).open(encoding="utf-8") as f:
        event = json.load(f)
    event_name = os.getenv("GITHUB_EVENT_NAME", "")
    files = changed_files(event, event_name,
                          os.getenv("GITHUB_REPOSITORY", ""),
                          os.getenv("GITHUB_TOKEN", ""))
    return event, event_name, files


def core_product_scope(product: str) -> dict[str, object]:
    """Focused Core plan for another product lane (Engine) or the safe full path."""
    plan: dict[str, object] | None = None
    try:
        _, _, files = _load_event_files()
        plan = core_focused_plan(REPO_ROOT, files, product)
    except (OSError, ValueError, KeyError, TypeError, TimeoutError):
        plan = None
    except Exception:
        # Network/API ambiguity must never silently shrink a CI test lane.
        plan = None
    if plan is None:
        return {"independent": False, "modules": [], "tests": []}
    return plan


def _core_product_argument() -> str | None:
    """Read the optional ``--core-product`` argument without argparse.

    The classifier is imported and called directly by its contract tests, so
    it must not consume or reject unrelated process arguments.
    """
    argv = sys.argv[1:]
    if "--core-product" not in argv:
        return None
    index = argv.index("--core-product")
    if index + 1 >= len(argv):
        return None
    product = argv[index + 1]
    return product if product in ("b62", "engine") else None


def main() -> None:
    if "--print-ui-contract" in sys.argv[1:]:
        print(" ".join(ui_contract_tests(REPO_ROOT)))
        return

    core_product = _core_product_argument()

    if core_product:
        plan = core_product_scope(core_product)
        modules = plan.get("modules") or []
        tests = plan.get("tests") or []
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as out:
            out.write(f"core_independent={'true' if plan.get('independent') else 'false'}\n")
            out.write(f"core_modules={' '.join(modules)}\n")
            out.write(f"core_tests={' '.join(tests)}\n")
        print(
            f"CORE_IMPACT_SCOPE={core_product}:"
            f"{'INDEPENDENT' if plan.get('independent') else 'FULL'}"
        )
        return

    scope = FULL
    static_changed = False
    chat_source = False
    ui_contract: tuple[str, ...] = ()
    ui_tests: tuple[str, ...] = ()
    tests_only_tests: tuple[str, ...] = ()
    core_tests: tuple[str, ...] = ()
    core_modules: tuple[str, ...] = ()
    try:
        event, event_name, files = _load_event_files()
        # An unprovable change set runs the full Chat suite (fail closed).
        chat_source = True if files is None else chat_source_changed(files)
        scope = impact_scope(files)
        static_changed = _has_static_change(files)
        if static_changed:
            # #6783: a static-only PR used to run no pytest module that reads
            # static. Every module that proves a shipped UI contract runs here.
            ui_contract = ui_contract_tests(REPO_ROOT)
            if not ui_contract:
                # An empty derivation is never evidence that a static change
                # is safe (unreadable sources, or the module cap overflowed).
                # Run the full Chat suite instead of skipping every pytest.
                print("B62_UI_CONTRACT_DISCOVERY=EMPTY", file=sys.stderr)
                chat_source = True
        if scope == UI_MIXED:
            # Require complete PR metadata, not just a possibly truncated
            # compare listing. Main pushes and incomplete PR metadata use FULL.
            pr = event.get("pull_request") if isinstance(event,dict) else None
            count = pr.get("changed_files") if isinstance(pr,dict) else None
            if event_name != "pull_request" or type(count) is not int or count != len(files):
                scope = FULL
            # #7599: A static+tests PR used to skip Chat full pytest, allowing
            # broken tests to merge green (#7617, #7618). Full Chat pytest runs
            # in ~8m15s (<10m), so UI_MIXED always runs full Chat pytest.
            chat_source = True
        ui_tests = ui_mixed_test_modules(files) if scope == UI_MIXED else ()
        if _is_tests_tree_change(files):
            # #6810: a tests-only PR used to run no pytest module at all; the
            # affected modules are now the load-bearing check.
            # #7186: the same proof decides the lane and the runner. When no
            # runnable set exists (helper nothing imports, conftest.py), the
            # reduced lane is not evidence and the full Chat suite must run --
            # the flag below is what selects that job.
            tests_only_tests = tests_only_modules(files, REPO_ROOT)
            if tests_only_tests:
                scope = TESTS_ONLY
            else:
                scope = FULL
                chat_source = True
        if scope == CORE_FOCUSED_ONLY:
            plan = core_focused_plan(REPO_ROOT, files, "b62")
            if plan is None:
                scope = FULL
            else:
                core_tests = tuple(plan.get("tests") or ())
                core_modules = tuple(plan.get("modules") or ())
    except (OSError, ValueError, KeyError, TypeError, TimeoutError):
        scope = FULL
        chat_source = True
    except Exception:
        # Network/API ambiguity must never silently shrink a CI test lane.
        scope = FULL
        chat_source = True
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as out:
        out.write(f"scope={scope}\n")
        out.write(f"static_changed={'true' if static_changed else 'false'}\n")
        out.write(f"chat_source_changed={'true' if chat_source else 'false'}\n")
        out.write(f"ui_contract={' '.join(ui_contract)}\n")
        out.write(f"ui_tests={' '.join(ui_tests)}\n")
        out.write(f"tests_only_tests={' '.join(tests_only_tests if scope == TESTS_ONLY else ())}\n")
        out.write(f"core_tests={' '.join(core_tests)}\n")
        out.write(f"core_modules={' '.join(core_modules)}\n")
    print(f"B62_CI_IMPACT_SCOPE={scope}")
    if static_changed:
        print(f"B62_UI_CONTRACT_MODULES={len(ui_contract)}")


if __name__ == "__main__":
    main()
