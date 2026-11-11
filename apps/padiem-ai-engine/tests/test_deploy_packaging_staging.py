"""Tests for the deploy-only Padiem AI Engine wheel staging seam."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


_SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "deploy-padiem-ai-engine.py"
_SPEC = importlib.util.spec_from_file_location("deploy_padiem_ai_engine", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def _canonical_pyproject() -> str:
    return """[build-system]\nrequires = [\"setuptools>=68\"]\nbuild-backend = \"setuptools.build_meta\"\n\n[project]\nname = \"padiem-ai-engine\"\nversion = \"0.1.0\"\ndependencies = [\n  \"httpx>=0.27,<1\",\n  \"padiem-ai-core @ file://${PROJECT_ROOT}/../../packages/padiem-ai-core\",\n]\n"""


def _canonical_wrangler() -> str:
    return """name = \"padiem-ai-engine\"\n# #4383: preserve operator-owned variables on deploy.\nkeep_vars = true\nmain = \"worker_identity.py\"\ncompatibility_date = \"2026-08-27\"\ncompatibility_flags = [\"python_workers\"]\nworkers_dev = false\n"""


def test_rewrite_staged_pyproject_points_only_staged_copy_to_wheel(tmp_path: Path) -> None:
    staged = tmp_path / "pyproject.toml"
    original = _canonical_pyproject()
    staged.write_text(original, encoding="utf-8")

    _MODULE.rewrite_staged_pyproject(staged, "padiem_ai_core-0.6.0-py3-none-any.whl")

    rewritten = staged.read_text(encoding="utf-8")
    assert "../../packages/padiem-ai-core" not in rewritten
    assert (
        'padiem-ai-core @ file://${PROJECT_ROOT}/.deploy-wheels/'
        "padiem_ai_core-0.6.0-py3-none-any.whl"
    ) in rewritten


def test_rewrite_staged_pyproject_fails_closed_on_dependency_drift(tmp_path: Path) -> None:
    staged = tmp_path / "pyproject.toml"
    staged.write_text("[project]\nname='other'\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Expected exactly one canonical"):
        _MODULE.rewrite_staged_pyproject(staged, "core.whl")


def test_validate_wrangler_contract_fails_closed_on_public_runtime_drift(tmp_path: Path) -> None:
    wrangler = tmp_path / "wrangler.toml"
    wrangler.write_text(_canonical_wrangler().replace("workers_dev = false", "workers_dev = true"), encoding="utf-8")

    with pytest.raises(RuntimeError, match="wrangler contract drifted"):
        _MODULE.validate_wrangler_contract(wrangler)


def test_prepare_staging_preserves_canonical_files_and_copies_wheel(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    engine = repo / "apps" / "padiem-ai-engine"
    app = engine / "app"
    app.mkdir(parents=True)
    canonical_pyproject = engine / "pyproject.toml"
    canonical_wrangler = engine / "wrangler.toml"
    canonical_worker = engine / "worker_identity.py"
    canonical_service = app / "service.py"
    canonical_pyproject.write_text(_canonical_pyproject(), encoding="utf-8")
    canonical_wrangler.write_text(_canonical_wrangler(), encoding="utf-8")
    canonical_worker.write_text("Default = object()\n", encoding="utf-8")
    canonical_service.write_text("EXECUTE_PATH = '/internal/v1/execute'\n", encoding="utf-8")

    wheel = tmp_path / "padiem_ai_core-0.6.0-py3-none-any.whl"
    wheel.write_bytes(b"synthetic-wheel-for-network-free-staging-test")
    original_pyproject = canonical_pyproject.read_bytes()
    original_wrangler = canonical_wrangler.read_bytes()
    original_worker = canonical_worker.read_bytes()
    original_service = canonical_service.read_bytes()

    stage = tmp_path / "stage"
    staged_wheel = _MODULE.prepare_staging(repo, stage, wheel)

    assert canonical_pyproject.read_bytes() == original_pyproject
    assert canonical_wrangler.read_bytes() == original_wrangler
    assert canonical_worker.read_bytes() == original_worker
    assert canonical_service.read_bytes() == original_service
    assert (stage / "worker_identity.py").read_bytes() == original_worker
    assert (stage / "app" / "service.py").read_bytes() == original_service
    assert (stage / "wrangler.toml").read_bytes() == original_wrangler
    assert staged_wheel.read_bytes() == wheel.read_bytes()
    assert "../../packages/padiem-ai-core" not in (stage / "pyproject.toml").read_text(encoding="utf-8")


def test_required_wrangler_snippets_match_the_current_engine_config() -> None:
    engine_wrangler = Path(__file__).resolve().parents[1] / "wrangler.toml"
    _MODULE.validate_wrangler_contract(engine_wrangler)

    assert 'binding = "B14_SERVICE"' not in _MODULE.WRANGLER_REQUIRED_SNIPPETS
    assert 'service = "ai-revenue-korean-ai-platform"' not in _MODULE.WRANGLER_REQUIRED_SNIPPETS
    assert "keep_vars = true" in _MODULE.WRANGLER_REQUIRED_SNIPPETS


def test_validate_wrangler_contract_requires_keep_vars(tmp_path: Path) -> None:
    wrangler = tmp_path / "wrangler.toml"
    wrangler.write_text(_canonical_wrangler().replace("keep_vars = true\n", ""), encoding="utf-8")

    with pytest.raises(RuntimeError, match="keep_vars"):
        _MODULE.validate_wrangler_contract(wrangler)


def test_deploy_uses_the_production_gate_keep_vars_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    gate = (
        Path(__file__).resolve().parents[3]
        / ".github"
        / "workflows"
        / "b54-engine-production-deploy-gate.yml"
    ).read_text(encoding="utf-8")
    assert "pywrangler deploy --keep-vars" in gate

    wrangler = tmp_path / "wrangler.toml"
    wrangler.write_text(_canonical_wrangler(), encoding="utf-8")
    calls: list[tuple[list[str], Path]] = []

    def fake_run(command: list[str], *, cwd: Path) -> None:
        calls.append((list(command), Path(cwd)))

    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "test-account")
    monkeypatch.setattr(_MODULE, "_run", fake_run)

    _MODULE.deploy_staged_engine(tmp_path)

    assert len(calls) == 1
    command, cwd = calls[0]
    assert cwd == tmp_path
    assert "--keep-vars" in command
    assert command[command.index("--config") + 1] == "wrangler.toml"
