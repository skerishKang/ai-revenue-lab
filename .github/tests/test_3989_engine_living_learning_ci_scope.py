"""#3989: prove Engine/Living Learning trigger ownership without weaker Core gates.

Paths are the actual GitHub Actions workflow declarations. No external calls.
The Engine test suite retains its Living Learning/Core cross-runtime regression
for every Engine or shared Core change; only Living Learning *alone* is excluded.
"""
from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
ENGINE_PATH = ROOT / ".github/workflows/padiem-ai-engine-ci.yml"
LIVING_PATH = ROOT / ".github/workflows/living-learning-padiem-core-ci.yml"
POLICY_PATH = ROOT / ".github/workflows/operations-policy-guard.yml"
SELF_PATH = ".github/tests/test_3989_engine_living_learning_ci_scope.py"


def workflow(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def events(data: dict) -> dict:
    # PyYAML's YAML 1.1 loader parses the unquoted on key as True.
    result = data.get("on", data.get(True))
    assert isinstance(result, dict)
    return result


def changed_paths(data: dict) -> tuple[str, ...]:
    source = events(data)["pull_request"]
    assert isinstance(source, dict)
    paths = source["paths"]
    assert isinstance(paths, list)
    return tuple(paths)


def triggered(paths: tuple[str, ...], files: tuple[str, ...]) -> bool:
    # The scope here uses only positive exact paths and recursive /** rules,
    # so this intentionally over-inclusive fnmatch matcher never understates
    # impact for representative repository paths.
    return any(fnmatchcase(name, glob) for name in files for glob in paths)


class TestEngineLLPathOwnership:
    def test_engine_owns_only_engine_core_and_self_validation(self):
        declared = changed_paths(workflow(ENGINE_PATH))
        assert declared == (
            "apps/padiem-ai-engine/**",
            "packages/padiem-ai-core/**",
            SELF_PATH,
            ".github/workflows/padiem-ai-engine-ci.yml",
        )

    def test_living_learning_owns_its_product_and_core(self):
        declared = changed_paths(workflow(LIVING_PATH))
        assert declared == (
            "apps/living-learning/**",
            "packages/padiem-ai-core/**",
            "scripts/experiments/benchmark_padiem_search_providers.py",
            "scripts/experiments/benchmark_padiem_fetch_providers.py",
            SELF_PATH,
            ".github/workflows/living-learning-padiem-core-ci.yml",
            ".github/scripts/living_learning_core_parallel_3989.sh",
            ".github/tests/test_3989_living_learning_parallel_scope.py",
        )

    def test_no_dropped_core_or_cross_product_regression(self):
        engine = ENGINE_PATH.read_text(encoding="utf-8")
        living = LIVING_PATH.read_text(encoding="utf-8")
        for required in (
            "Engine network-free tests",
            "Padiem AI Core full tests",
            "Living Learning Core-reuse regression",
            "JavaScript Service Binding client tests",
            "Real Worker/Pyodide Drive external transport probe",
            "Python Worker bundle dry-run",
        ):
            assert required in engine
        for required in ("Living Learning full tests", "Padiem AI Core full tests",
                         "Prove default provider remains mock"):
            assert required in living

    def test_manual_dispatch_and_per_pr_cancellation_remain(self):
        for path in (ENGINE_PATH, LIVING_PATH):
            data = workflow(path)
            assert "workflow_dispatch" in events(data)
            assert data["concurrency"]["cancel-in-progress"] is True
            assert "github.event.pull_request.number || github.run_id" in data["concurrency"]["group"]
            assert data["permissions"]["contents"] == "read"

    def test_canonical_impact_matrix(self):
        engine = changed_paths(workflow(ENGINE_PATH))
        living = changed_paths(workflow(LIVING_PATH))
        cases = {
            "ll_only": (("apps/living-learning/app/session.py",), (False, True)),
            "ll_test_only": (("apps/living-learning/tests/test_session.py",), (False, True)),
            "engine_only": (("apps/padiem-ai-engine/app/service.py",), (True, False)),
            "engine_worker_only": (("apps/padiem-ai-engine/worker.py",), (True, False)),
            "core_only": (("packages/padiem-ai-core/padiem_ai_core/tool_runtime.py",), (True, True)),
            "mixed_engine_ll": (("apps/living-learning/app/factory.py", "apps/padiem-ai-engine/app/services.py"), (True, True)),
            "mixed_core_ll": (("packages/padiem-ai-core/padiem_ai_core/execution_runtime.py", "apps/living-learning/app/provider.py"), (True, True)),
            "docs_only": (("docs/operations/CI_3989_ENGINE_LL_ROUTING.md",), (False, False)),
            "shared_identity": (("packages/padiem-control-plane/padiem_control_plane/identity.py",), (False, False)),
            "engine_workflow": ((".github/workflows/padiem-ai-engine-ci.yml",), (True, False)),
            "ll_workflow": ((".github/workflows/living-learning-padiem-core-ci.yml",), (False, True)),
            "policy_test": ((SELF_PATH,), (True, True)),
        }
        for name, (files, expected) in cases.items():
            assert (triggered(engine, files), triggered(living, files)) == expected, name



    def test_engine_core_ll_parallel_runner_keeps_both_fail_closed_suites(self):
        engine = ENGINE_PATH.read_text(encoding="utf-8")
        script = (ROOT / ".github/scripts/engine_core_ll_parallel_3989.sh").read_text(encoding="utf-8")
        assert "name: Padiem AI Core full tests and Living Learning Core-reuse regression" in engine
        assert "run: bash .github/scripts/engine_core_ll_parallel_3989.sh" in engine
        for required in (
            "uv run --extra dev python -m pytest -q",
            "python -m pip install --disable-pip-version-check -r requirements-padiem-core.txt",
            "python -m pip install --disable-pip-version-check -e '.[dev]'",
            "python -m pip install --disable-pip-version-check 'jsonschema>=4.23,<5'",
            "python -m pip check",
            "python -m pytest -q",
            "export LL_PROVIDER_TYPE=mock",
            'wait "$core_pid"',
            'wait "$ll_pid"',
            'if [[ "$core_status" -ne 0 || "$ll_status" -ne 0 ]]',
            "ENGINE_CORE_LL_PARALLEL=PASS",
        ):
            assert required in script

    def test_policy_guard_enforces_scope_contract(self):
        text = POLICY_PATH.read_text(encoding="utf-8")
        assert "python -m pytest -q .github/tests/test_3989_engine_living_learning_ci_scope.py" in text
