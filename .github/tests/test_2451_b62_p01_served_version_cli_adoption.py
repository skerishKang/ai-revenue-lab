"""#2451: B62 P01 binding mutation reads reuse canonical served-version CLI."""

from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "b62-p01-engine-service-binding-gate.yml"
CLI = ROOT / ".github" / "scripts" / "cloudflare_served_version_cli.py"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _step(job: str, name: str) -> str:
    steps = _workflow()["jobs"][job]["steps"]
    matches = [step["run"] for step in steps if step.get("name") == name]
    assert len(matches) == 1
    return matches[0]


def test_premutation_reads_fail_closed_through_generic_cli() -> None:
    for job, name in (
        ("activate-p01-engine-binding", "Capture exact pre-mutation Worker state"),
        ("rollback-p01-engine-binding", "Capture exact pre-rollback Worker state"),
    ):
        run = _step(job, name)
        assert run.count("cloudflare_served_version_cli.py resolve-active") == 1
        assert 'active="$(python3 .github/scripts/cloudflare_served_version_cli.py resolve-active' in run
        assert 'if ! active=' not in run
        assert 'test "${active}" = "${latest}"' in run
        assert ".result.deployments[0].versions[0]" not in run


def test_postmutation_and_rollback_polls_preserve_30x2s_budget() -> None:
    for job, name in (
        ("activate-p01-engine-binding", "Read back exact post-mutation state"),
        ("rollback-p01-engine-binding", "Read back rollback exactness"),
    ):
        run = _step(job, name)
        assert "for _ in $(seq 1 30)" in run
        assert "sleep 2" in run
        assert run.count("cloudflare_served_version_cli.py resolve-active") == 1
        assert 'if ! active="$(python3 .github/scripts/cloudflare_served_version_cli.py resolve-active' in run
        assert 'active=""' in run
        assert '[ "${active}" != "${BEFORE_VERSION}" ]' in run
        assert ".result.deployments[0].versions[0]" not in run


def test_readonly_keeps_existing_python_resolver_authority() -> None:
    readonly = "\n".join(
        step.get("run", "")
        for step in _workflow()["jobs"]["cloudflare-readonly"]["steps"]
        if "run" in step
    )
    assert "from cloudflare_served_version import" in readonly
    assert "resolve_served_version_id" in readonly
    assert "cloudflare_served_version_cli.py resolve-active" not in readonly


def test_trigger_paths_include_generic_cli_and_existing_resolver() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    trigger_paths = text.split("on:", 1)[1].split("workflow_dispatch:", 1)[0]
    assert ".github/scripts/cloudflare_served_version.py" in trigger_paths
    assert ".github/scripts/cloudflare_served_version_cli.py" in trigger_paths
    assert ".github/tests/test_cloudflare_served_version.py" in trigger_paths
    assert CLI.is_file()
