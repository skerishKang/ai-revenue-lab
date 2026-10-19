"""Regression tests for the cross-lane test dependency guard (#3625).

The guard prevents a workflow from collecting another component's pytest test
tree without the environment that tree needs at import/collection time, the
coupling class proven by the #3593 merge-forward incident.

Six proofs are pinned here:

1. the real repository passes;
2. collecting a component tree with no dependency bootstrap fails;
3. a shared conftest that grows a dependency fails the collecting lane;
4. a canonical bootstrap (uv or a pip-resolvable editable install) passes;
5. an unrelated repo-harness-only workflow is not affected;
6. a source-only / lazily-importing workflow is not a false positive.

Nothing here hardcodes ``httpx``/``starlette`` beyond reusing them in the #3593
reproduction fixture.
"""

from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github" / "scripts" / "cross_lane_test_dependency_guard.py"
_spec = importlib.util.spec_from_file_location("cross_lane_test_dependency_guard", SCRIPT)
assert _spec and _spec.loader
guard = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = guard
_spec.loader.exec_module(guard)


# --------------------------------------------------------------------------- #
# fixture builders
# --------------------------------------------------------------------------- #
def _build_repo(
    root: Path,
    workflow_name: str,
    workflow_text: str,
    *,
    conftest: str,
    dependencies: list[str],
    test_module: str = (
        "from __future__ import annotations\n\nimport pathlib\n\n\n"
        "def test_sample() -> None:\n    assert pathlib.Path('.').exists()\n"
    ),
    with_conftest: bool = True,
) -> Path:
    workflows = root / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    (workflows / workflow_name).write_text(
        textwrap.dedent(workflow_text).lstrip("\n"), encoding="utf-8"
    )

    component = root / "apps" / "widget"
    (component / "app").mkdir(parents=True, exist_ok=True)
    (component / "app" / "__init__.py").write_text("", encoding="utf-8")
    (component / "tests").mkdir(parents=True, exist_ok=True)
    if with_conftest:
        (component / "tests" / "conftest.py").write_text(
            textwrap.dedent(conftest).lstrip("\n"), encoding="utf-8"
        )
    (component / "tests" / "test_sample.py").write_text(test_module, encoding="utf-8")

    dep_lines = "".join(f'  "{dep}",\n' for dep in dependencies)
    (component / "pyproject.toml").write_text(
        '[project]\nname = "widget"\nversion = "0.1.0"\ndependencies = [\n'
        f"{dep_lines}]\n",
        encoding="utf-8",
    )
    return root


def _codes(violations: list[guard.Violation], workflow: str) -> set[tuple[str, str]]:
    return {(v.code, v.detail) for v in violations if v.workflow == workflow}


# --------------------------------------------------------------------------- #
# proof 1 - the real repository is valid
# --------------------------------------------------------------------------- #
def test_guard_passes_on_repository() -> None:
    violations, stats = guard.evaluate(ROOT)
    assert violations == [], [v.render() for v in violations]
    assert stats["workflows_scanned"] > 0
    # The shared-harness coupling classes are present and covered.
    assert stats["conftest_couplings"] > 0
    assert stats["component_collections"] > 0


def test_guard_main_reports_acceptance_tokens(capsys: pytest.CaptureFixture[str]) -> None:
    assert guard.main(["--repo", str(ROOT)]) == 0
    out = capsys.readouterr().out
    assert "CROSS_LANE_DEPENDENCY_GUARD=PASS" in out
    assert "SHARED_TEST_HARNESS_COUPLING_DETECTED=YES" in out
    assert "AD_HOC_DEPENDENCY_DRIFT_GUARDED=YES" in out
    assert "PRODUCT_SOURCE_CHANGE=NO" in out
    assert "MODEL_PROVIDER_CHANGE=NO" in out
    assert "PRODUCTION_MUTATION=0" in out


# --------------------------------------------------------------------------- #
# proof 2 + the #3593 reproduction - no bootstrap -> FAIL
# --------------------------------------------------------------------------- #
_3593_CONFTEST = """
    from __future__ import annotations

    import httpx
    import pytest
    from starlette import testclient as starlette_testclient

    import app
    """


def test_collecting_component_tree_without_bootstrap_fails(tmp_path: Path) -> None:
    repo = _build_repo(
        tmp_path,
        "collect.yml",
        """
        name: collect
        on: {pull_request: {}}
        jobs:
          t:
            runs-on: ubuntu-latest
            steps:
              - name: install
                run: python -m pip install --quiet pytest
              - name: run
                run: python -m pytest -q apps/widget/tests/test_sample.py
        """,
        conftest=_3593_CONFTEST,
        dependencies=["httpx>=0.27,<1"],
    )
    violations, _ = guard.evaluate(repo)
    found = _codes(violations, "collect.yml")
    assert ("MISSING_FIRST_PARTY_ROOT", "app (expected apps/widget importable)") in found
    assert ("MISSING_THIRD_PARTY_DEP", "httpx (collected tree imports it; install a provider)") in found
    assert ("MISSING_THIRD_PARTY_DEP", "starlette (collected tree imports it; install a provider)") in found


def test_3593_reproduction_adds_bootstrap_then_passes(tmp_path: Path) -> None:
    """The exact #3593 shape: pytest-only collection dies on the shared conftest."""
    repo = _build_repo(
        tmp_path,
        "collect.yml",
        """
        name: collect
        on: {pull_request: {}}
        jobs:
          t:
            runs-on: ubuntu-latest
            steps:
              - name: install
                run: |
                  set -euo pipefail
                  python -m pip install --quiet pytest 'httpx>=0.27,<1' 'starlette>=0.37,<1'
              - name: run
                env:
                  PYTHONPATH: apps/widget
                run: python -m pytest -q apps/widget/tests/test_sample.py
        """,
        conftest=_3593_CONFTEST,
        dependencies=["httpx>=0.27,<1", "starlette>=0.37,<1"],
    )
    violations, _ = guard.evaluate(repo)
    assert violations == [], [v.render() for v in violations]


# --------------------------------------------------------------------------- #
# proof 3 - shared conftest dependency growth -> FAIL
# --------------------------------------------------------------------------- #
def test_shared_conftest_dependency_growth_breaks_the_collecting_lane(
    tmp_path: Path,
) -> None:
    workflow = """
        name: collect
        on: {pull_request: {}}
        jobs:
          t:
            runs-on: ubuntu-latest
            steps:
              - name: install
                run: python -m pip install --quiet pytest
              - name: run
                env:
                  PYTHONPATH: apps/widget
                run: python -m pytest -q apps/widget/tests/test_sample.py
        """
    # Baseline: the shared conftest imports nothing outside the component.
    repo = _build_repo(
        tmp_path,
        "collect.yml",
        workflow,
        conftest="import app\n",
        dependencies=[],
    )
    violations, _ = guard.evaluate(repo)
    assert violations == [], [v.render() for v in violations]

    # Representative growth: the same shared conftest gains a new dependency.
    (repo / "apps/widget/tests/conftest.py").write_text(
        "import anyio\n\nimport app\n", encoding="utf-8"
    )
    violations, _ = guard.evaluate(repo)
    found = _codes(violations, "collect.yml")
    assert ("MISSING_THIRD_PARTY_DEP", "anyio (collected tree imports it; install a provider)") in found
    assert (
        "UNDECLARED_THIRD_PARTY_TEST_IMPORT",
        "anyio (not declared by apps/widget/pyproject.toml)",
    ) in found


# --------------------------------------------------------------------------- #
# proof 4 - canonical bootstrap -> PASS
# --------------------------------------------------------------------------- #
def test_canonical_uv_bootstrap_passes(tmp_path: Path) -> None:
    repo = _build_repo(
        tmp_path,
        "canonical.yml",
        """
        name: canonical
        on: {pull_request: {}}
        jobs:
          t:
            runs-on: ubuntu-latest
            defaults:
              run:
                working-directory: apps/widget
            steps:
              - name: sync
                run: uv sync --locked --extra dev
              - name: run
                run: uv run --locked python -m pytest -q tests/test_sample.py
        """,
        conftest=_3593_CONFTEST,
        dependencies=["httpx>=0.27,<1"],
    )
    violations, _ = guard.evaluate(repo)
    assert violations == [], [v.render() for v in violations]


def test_canonical_pip_editable_component_passes(tmp_path: Path) -> None:
    repo = _build_repo(
        tmp_path,
        "editable.yml",
        """
        name: editable
        on: {pull_request: {}}
        jobs:
          t:
            runs-on: ubuntu-latest
            defaults:
              run:
                working-directory: apps/widget
            steps:
              - name: install
                run: python -m pip install -e '.[dev]'
              - name: run
                run: python -m pytest -q tests/test_sample.py
        """,
        conftest="import app\nimport httpx\n",
        dependencies=["httpx>=0.27,<1"],
    )
    violations, _ = guard.evaluate(repo)
    assert violations == [], [v.render() for v in violations]


def test_pip_editable_with_uv_only_template_is_not_canonical(tmp_path: Path) -> None:
    """``pip install -e`` cannot resolve ``file://${PROJECT_ROOT}`` deps.

    The editable install therefore cannot be trusted as a canonical bootstrap,
    and the guard falls back to the explicit closure.
    """
    repo = _build_repo(
        tmp_path,
        "uvtemplate.yml",
        """
        name: uvtemplate
        on: {pull_request: {}}
        jobs:
          t:
            runs-on: ubuntu-latest
            defaults:
              run:
                working-directory: apps/widget
            steps:
              - name: install
                run: python -m pip install -e .
              - name: run
                run: python -m pytest -q tests/test_sample.py
        """,
        conftest="import app\nimport httpx\n",
        dependencies=["httpx>=0.27,<1", "sibling @ file://${PROJECT_ROOT}/../sibling"],
    )
    violations, _ = guard.evaluate(repo)
    found = _codes(violations, "uvtemplate.yml")
    assert ("MISSING_THIRD_PARTY_DEP", "httpx (collected tree imports it; install a provider)") in found


# --------------------------------------------------------------------------- #
# proof 5 - unrelated repo-harness workflow is unaffected
# --------------------------------------------------------------------------- #
def test_unrelated_harness_workflow_is_unaffected(tmp_path: Path) -> None:
    repo = _build_repo(
        tmp_path,
        "collect.yml",
        """
        name: collect
        on: {pull_request: {}}
        jobs:
          t:
            runs-on: ubuntu-latest
            steps:
              - name: run
                run: python -m pytest -q apps/widget/tests/test_sample.py
        """,
        conftest="import httpx\n\nimport app\n",
        dependencies=["httpx>=0.27,<1"],
    )
    (repo / ".github" / "tests").mkdir(parents=True, exist_ok=True)
    (repo / ".github" / "tests" / "test_harness.py").write_text(
        "def test_harness() -> None:\n    assert True\n", encoding="utf-8"
    )
    (repo / ".github" / "workflows" / "harness.yml").write_text(
        textwrap.dedent(
            """
            name: harness
            on: {pull_request: {}}
            jobs:
              h:
                runs-on: ubuntu-latest
                steps:
                  - name: install
                    run: python -m pip install --quiet pytest
                  - name: run
                    run: python -m pytest -q .github/tests/test_harness.py
            """
        ).lstrip("\n"),
        encoding="utf-8",
    )
    violations, _ = guard.evaluate(repo)
    assert all(v.workflow != "harness.yml" for v in violations)
    # The coupled workflow is still reported.
    assert any(v.workflow == "collect.yml" for v in violations)


# --------------------------------------------------------------------------- #
# proof 6 - source-only and lazily-importing workflows are not false positives
# --------------------------------------------------------------------------- #
def test_source_only_workflow_and_lazy_import_are_not_flagged(tmp_path: Path) -> None:
    repo = _build_repo(
        tmp_path,
        "source-only.yml",
        """
        name: source-only
        on: {pull_request: {}}
        jobs:
          s:
            runs-on: ubuntu-latest
            steps:
              - name: compile
                run: |
                  set -euo pipefail
                  python -m compileall -q apps/widget/app
                  python .github/scripts/not_a_test.py
        """,
        conftest="import app\n",
        dependencies=[],
    )
    (repo / ".github" / "scripts").mkdir(parents=True, exist_ok=True)
    (repo / ".github" / "scripts" / "not_a_test.py").write_text(
        "print('source only')\n", encoding="utf-8"
    )
    # A component tree whose test module imports the app lazily (inside a
    # function), exactly like apps/padiem-ai-engine: nothing to import at
    # collection time, so no bootstrap is required.
    (repo / ".github" / "workflows" / "lazy.yml").write_text(
        textwrap.dedent(
            """
            name: lazy
            on: {pull_request: {}}
            jobs:
              l:
                runs-on: ubuntu-latest
                steps:
                  - name: install
                    run: python -m pip install --quiet pytest
                  - name: run
                    run: python -m pytest -q apps/widget/tests/test_sample.py
            """
        ).lstrip("\n"),
        encoding="utf-8",
    )
    (repo / "apps" / "widget" / "tests" / "conftest.py").unlink()
    (repo / "apps" / "widget" / "tests" / "test_sample.py").write_text(
        "from __future__ import annotations\n\nimport pytest\n\n\n"
        "def test_lazy() -> None:\n"
        "    from app import model_registry\n\n"
        "    assert model_registry is not None\n",
        encoding="utf-8",
    )
    violations, _ = guard.evaluate(repo)
    assert violations == [], [v.render() for v in violations]


def test_conftest_self_bootstrap_is_recognized(tmp_path: Path) -> None:
    """A conftest that inserts its own source root is importable without env."""
    repo = _build_repo(
        tmp_path,
        "selfboot.yml",
        """
        name: selfboot
        on: {pull_request: {}}
        jobs:
          t:
            runs-on: ubuntu-latest
            steps:
              - name: install
                run: python -m pip install --quiet pytest
              - name: run
                run: python -m pytest -q apps/widget/tests/test_sample.py
        """,
        conftest=(
            "import sys\n"
            "from pathlib import Path\n"
            "\n"
            "sys.path.insert(0, str(Path(__file__).resolve().parent.parent))\n"
            "\n"
            "import app\n"
        ),
        dependencies=[],
    )
    violations, _ = guard.evaluate(repo)
    assert violations == [], [v.render() for v in violations]
