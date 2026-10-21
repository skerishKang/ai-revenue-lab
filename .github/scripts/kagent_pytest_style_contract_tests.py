"""Run the KAgent pytest-style suites that the unittest lane cannot collect.

The KAgent CI lane discovers ``unittest.TestCase`` cases only:

    unittest.TestLoader().discover(start_dir="tests", pattern="test*.py")

A pytest-style module (module-level ``test_*`` functions, ``parametrize``, no
``TestCase``) contributes **zero** cases, so every assertion in it ran only
wherever a developer happened to invoke pytest by hand. A module that mixes
both styles is worse: its ``TestCase`` methods are collected, and its
module-level pytest function next to them is invisible.

This helper derives the exact complementary set from the *same* discovery the
unittest lane uses and hands only that set to pytest. The two lanes therefore
cover every test function in the package and neither runs a test twice:

* a file with no unittest case at all is passed as a whole file;
* a mixed file contributes only the node IDs of its uncollected functions.

Selection is by exact ``(class, function)`` identity rather than by counting
test functions. A count is wrong in both directions: inherited test methods
from a shared base class make the unittest side look larger, and a module
level pytest function is invisible to it.

Read-only with respect to the product: it collects and runs tests, and it
never edits a test, a fixture or an assertion.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

TESTS_DIR = "tests"
PATTERN = "test*.py"


def _flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _flatten(item)
        else:
            yield item


def _collected_identities() -> tuple[dict[str, set[tuple[str | None, str]]], int]:
    """Exact (class, function) identities the unittest lane collects."""
    suite = unittest.TestLoader().discover(start_dir=TESTS_DIR, pattern=PATTERN)
    cases = list(_flatten(suite))
    identities: dict[str, set[tuple[str | None, str]]] = {}
    for case in cases:
        parts = case.id().split(".")
        module = parts[0]
        if len(parts) == 2:
            identity = (None, parts[1])
        else:
            identity = (parts[-2], parts[-1])
        identities.setdefault(module, set()).add(identity)
    return identities, len(cases)


def _import_failures() -> list[str]:
    """Modules unittest could not import, by the name it reported.

    unittest turns an import error into a ``_FailedTest`` placeholder, which
    is not the module's own case. Without this check such a module looks
    exactly like a pytest-style module that contributed no case, and it would
    be handed to pytest as if it were a legitimate selection. That is a
    broken environment, not a collection gap, so it must stop the lane.
    """
    suite = unittest.TestLoader().discover(start_dir=TESTS_DIR, pattern=PATTERN)
    failed: list[str] = []
    for case in _flatten(suite):
        if type(case).__name__ != "_FailedTest":
            continue
        parts = case.id().split(".")
        failed.append(parts[-1])
    return sorted(set(failed))


def _declared_test_functions(path: Path) -> list[tuple[str | None, str]]:
    """Every ``test_*`` function the file declares, module level or method."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[str | None, str]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            found.append((None, node.name))
        elif isinstance(node, ast.ClassDef):
            for member in node.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and member.name.startswith("test"):
                    found.append((node.name, member.name))
    return found


def _select() -> tuple[list[str], list[str]]:
    """Return (pytest arguments, human readable selection notes)."""
    identities, collected_total = _collected_identities()
    if collected_total == 0:
        print(
            "KAGENT_PYTEST_STYLE_NO_UNITTEST_BASELINE "
            "the unittest lane collected no case, so the complementary set "
            "cannot be derived",
            file=sys.stderr,
        )
        raise SystemExit(2)

    args: list[str] = []
    notes: list[str] = []
    import_failures = _import_failures()
    if import_failures:
        print(
            "KAGENT_PYTEST_STYLE_IMPORT_FAILURE "
            f"modules={len(import_failures)} "
            + ",".join(import_failures[:20]),
            file=sys.stderr,
        )
        raise SystemExit(2)
    for path in sorted(Path(TESTS_DIR).glob(PATTERN)):
        module = path.stem
        declared = _declared_test_functions(path)
        if not declared:
            continue
        have = identities.get(module, set())
        uncollected = [identity for identity in declared if identity not in have]
        if not uncollected:
            continue
        if not have:
            # Nothing in this file is unittest-collectible, so the whole file
            # is uncollected and pytest may take it as a whole.
            args.append(path.as_posix())
            notes.append(f"{path.as_posix()}:{len(uncollected)}")
        else:
            # Mixed file: hand pytest only the functions the unittest lane
            # does not run, so its TestCase methods are not executed twice.
            for _class_name, function_name in uncollected:
                args.append(f"{path.as_posix()}::{function_name}")
                notes.append(f"{path.as_posix()}::{function_name}")
    return args, notes


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")

    args, notes = _select()
    if not args:
        print("KAGENT_PYTEST_STYLE_EMPTY every test function is unittest-collected")
        return 0

    print(
        f"KAGENT_PYTEST_STYLE_SELECTED targets={len(args)} "
        f"files={len({note.split(':')[0] for note in notes})}",
        flush=True,
    )
    for note in notes:
        print(f"KAGENT_PYTEST_STYLE_TARGET {note}", flush=True)

    command = [sys.executable, "-m", "pytest", "-q", "-o", "addopts=", *args]
    started = time.monotonic()
    completed = subprocess.run(
        command,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        cwd=os.getcwd(),
        shell=False,
    )
    elapsed = time.monotonic() - started
    if completed.returncode != 0:
        print(
            f"KAGENT_PYTEST_STYLE_FAILED targets={len(args)} exit={completed.returncode}",
            file=sys.stderr,
        )
        return completed.returncode
    print(
        f"KAGENT_PYTEST_STYLE_PASS targets={len(args)} seconds={elapsed:.1f}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
