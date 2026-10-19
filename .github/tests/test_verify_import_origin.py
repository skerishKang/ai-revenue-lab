"""#3658 contract tests for the import-origin preflight.

Four controls are required by the Issue, and all four are here:

1. a package that resolves inside the current checkout passes;
2. a package resolving to a different worktree fails fast, proven end to end through the real Core
   `conftest.py` hook rather than only through the function;
3. the same repository reached from its package root passes;
4. third-party and stdlib dependencies are never constrained, because they are not in the default
   set and the guard only judges names a lane asks it to judge.

Plus a divergence control asserting the neutral script and #3108's `kagent/dev_environment.py`
reach the same verdict for the same modules, which is the safe place for that coupling: the script
must not import the KAgent lane at runtime (#3625).
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "verify_import_origin.py"
SPEC = importlib.util.spec_from_file_location("verify_import_origin", SCRIPT)
assert SPEC and SPEC.loader
guard = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = guard
SPEC.loader.exec_module(guard)

KAGENT_VERIFIER = ROOT / "apps/korean-ai-code-agent/src/kagent/dev_environment.py"
CORE_TESTS = ROOT / "packages/padiem-ai-core/tests/test_b66_e2e_fixture_corpus.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _fake_resolver(roots: dict[str, str]):
    """A resolver stand-in so origins can be asserted without touching a real interpreter."""

    def resolve(module: str) -> tuple[str | None, str]:
        return roots.get(module), ""

    return resolve


# --------------------------------------------------------------------------- #
# 1 and 3. current checkout resolves inside -> pass
# --------------------------------------------------------------------------- #


def test_origin_inside_the_checkout_passes(tmp_path: Path) -> None:
    inside = tmp_path / "packages/padiem-ai-core/padiem_ai_core/__init__.py"
    inside.parent.mkdir(parents=True)
    inside.write_text("", encoding="utf-8")

    verdict = guard.check_origins(
        ("padiem_ai_core",), tmp_path, _fake_resolver({"padiem_ai_core": str(inside)})
    )

    assert verdict.ok
    assert verdict.summary().startswith("IMPORT_ORIGIN_CHECK=PASSED")


def test_real_import_of_a_local_package_resolves_inside_its_own_tree(tmp_path: Path) -> None:
    """A genuine interpreter import, not a stand-in: sys.path entry -> origin under that root."""

    pkg = tmp_path / "synth_local_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")

    sys.path.insert(0, str(tmp_path))
    try:
        verdict = guard.check_origins(("synth_local_pkg",), tmp_path)
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("synth_local_pkg", None)

    assert verdict.ok, verdict.origins


def test_core_suite_runs_when_the_tree_is_pinned(tmp_path: Path) -> None:
    """Control 3 end to end: PYTHONPATH at this checkout's Core is accepted by the real hook."""

    env = {**os.environ, "PYTHONPATH": str(ROOT / "packages/padiem-ai-core")}
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--collect-only", str(CORE_TESTS),
         "-p", "no:cacheprovider", "-o", "addopts="],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=env,
    )

    assert "resolves outside this checkout" not in proc.stdout + proc.stderr
    assert proc.returncode != 4, proc.stdout + proc.stderr


# --------------------------------------------------------------------------- #
# 2. a foreign worktree resolves the import -> fail fast
# --------------------------------------------------------------------------- #


def test_foreign_origin_is_an_offender(tmp_path: Path) -> None:
    foreign = tmp_path / "other-worktree/packages/padiem-ai-core/padiem_ai_core/__init__.py"
    foreign.parent.mkdir(parents=True)
    foreign.write_text("", encoding="utf-8")
    here = tmp_path / "this-worktree"
    here.mkdir()

    verdict = guard.check_origins(
        ("padiem_ai_core",), here, _fake_resolver({"padiem_ai_core": str(foreign)})
    )

    assert not verdict.ok
    assert [o.module for o in verdict.foreign] == ["padiem_ai_core"]
    lines = guard.diagnostic(verdict)
    assert any(line.startswith("FOREIGN padiem_ai_core") for line in lines)
    assert any(f"ACTUAL_ORIGIN={foreign.resolve()}" in line for line in lines)


def test_prefix_sibling_directory_is_not_mistaken_for_the_checkout(tmp_path: Path) -> None:
    """`padiem-ai-core-old` shares a name prefix with `padiem-ai-core` and must not compare equal."""

    root = tmp_path / "repo/packages/padiem-ai-core"
    lookalike = tmp_path / "repo/packages/padiem-ai-core-old"
    for path in (root, lookalike):
        (path / "padiem_ai_core").mkdir(parents=True)
        (path / "padiem_ai_core/__init__.py").write_text("", encoding="utf-8")

    verdict = guard.check_origins(
        ("padiem_ai_core",),
        root,
        _fake_resolver({"padiem_ai_core": str(lookalike / "padiem_ai_core/__init__.py")}),
    )

    assert verdict.foreign


def test_core_conftest_refuses_a_foreign_import_before_collecting(tmp_path: Path) -> None:
    """Control 2 end to end, through the real hook: a poisoned path is a refusal, not a green run."""

    decoy = tmp_path / "other-lane-worktree"
    core = decoy / "packages/padiem-ai-core/padiem_ai_core"
    core.mkdir(parents=True)
    (core / "__init__.py").write_text("__version__ = 'from-another-lane'\n", encoding="utf-8")

    env = {**os.environ, "PYTHONPATH": str(decoy / "packages/padiem-ai-core")}
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--collect-only", str(CORE_TESTS),
         "-p", "no:cacheprovider", "-o", "addopts="],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=env,
    )
    output = proc.stdout + proc.stderr

    # pytest.UsageError from pytest_configure exits 4 and never reaches collection.
    assert proc.returncode == 4, output
    assert "padiem_ai_core resolves outside this checkout" in output
    assert f"ACTUAL_ORIGIN={core.resolve()}" in output.replace("\r\n", "\n") or str(core.resolve()) in output
    assert "EXPECTED_CHECKOUT_ROOT=" in output


# --------------------------------------------------------------------------- #
# 4. third-party dependencies are unconstrained
# --------------------------------------------------------------------------- #


def test_default_module_set_contains_only_repository_packages() -> None:
    stdlib_and_third_party = {"json", "os", "sys", "pytest", "pathlib", "importlib", "yaml"}
    assert set(guard.DEFAULT_MODULES).isdisjoint(stdlib_and_third_party)
    assert guard.DEFAULT_MODULES == ("padiem_ai_core", "padiem_control_plane", "padiem_ai_engine_client")


def test_an_unimportable_module_is_absent_not_a_finding(tmp_path: Path) -> None:
    verdict = guard.check_origins(("definitely_not_installed_xyz",), tmp_path)

    assert verdict.ok
    assert verdict.foreign == ()
    assert any(line.startswith("ABSENT") for line in guard.diagnostic(verdict))


def test_a_package_that_raises_on_import_fails_closed(tmp_path: Path) -> None:
    """A module present but exploding is not the same as absent; it must not read as clean."""

    def resolver(_module: str) -> tuple[str | None, str]:
        return None, "import raised RuntimeError"

    verdict = guard.check_origins(("broken_pkg",), tmp_path, resolver)
    assert not verdict.ok
    assert [o.module for o in verdict.broken] == ["broken_pkg"]


# --------------------------------------------------------------------------- #
# diagnostics
# --------------------------------------------------------------------------- #


def test_diagnostic_carries_only_the_three_declared_fields(tmp_path: Path) -> None:
    foreign = tmp_path / "elsewhere/padiem_ai_core/__init__.py"
    foreign.parent.mkdir(parents=True)
    foreign.write_text("", encoding="utf-8")
    verdict = guard.check_origins(
        ("padiem_ai_core",), tmp_path / "here", _fake_resolver({"padiem_ai_core": str(foreign)})
    )

    text = "\n".join(guard.diagnostic(verdict))
    assert "EXPECTED_CHECKOUT_ROOT=" in text
    assert "ACTUAL_ORIGIN=" in text
    # No interpreter configuration or environment leakage in the report.
    for token in ("sys.path", "PYTHONPATH=", "environ", "PATH="):
        assert token not in text, token


def test_cli_exit_codes_are_deterministic(tmp_path: Path) -> None:
    """Uses a unique module name: `import_module` honors sys.modules, so reusing a real package
    name could return a cached foreign module and make the assertion depend on test order."""

    name = "synth_pkg_for_cli_exit_codes"
    pkg = tmp_path / "checkout" / name
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")

    sys.path.insert(0, str(tmp_path / "checkout"))
    try:
        passed = guard.main(
            ["--root", str(tmp_path / "checkout"), "--modules", name], writer=lambda _s: None
        )
        failed = guard.main(
            ["--root", str(tmp_path / "a-different-checkout"), "--modules", name],
            writer=lambda _s: None,
        )
    finally:
        sys.path.remove(str(tmp_path / "checkout"))
        sys.modules.pop(name, None)

    assert passed == 0
    assert failed == 1


# --------------------------------------------------------------------------- #
# divergence with #3108's verifier
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(not KAGENT_VERIFIER.exists(), reason="KAgent verifier moved; check intentionally")
def test_agrees_with_the_kagent_3108_verifier_on_the_same_environment() -> None:
    """Two implementations must not disagree about where an import came from.

    This is the only place the KAgent lane is touched. `verify_import_origin.py` deliberately does
    not import it at runtime, so a Core session never gains a cross-lane collection dependency.
    """

    kagent_env = _load(KAGENT_VERIFIER, "kagent_dev_environment_for_comparison")

    ours = guard.check_origins(guard.DEFAULT_MODULES, ROOT)
    theirs = kagent_env.describe_import_origins(guard.DEFAULT_MODULES, ROOT)

    theirs_by_module = {origin.module: origin for origin in theirs.origins}
    for origin in ours.origins:
        counterpart = theirs_by_module[origin.module]
        if origin.origin is None or counterpart.origin is None:
            # Both agree the module is not importable here; inside-ness is then undefined.
            assert (origin.origin is None) == (counterpart.origin is None), origin.module
            continue
        assert origin.inside_repository == counterpart.inside_repository, origin.module

    assert set(ours.summary())  # the neutral script reports without raising either way
