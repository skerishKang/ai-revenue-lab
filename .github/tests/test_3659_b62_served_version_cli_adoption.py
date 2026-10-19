"""#3659: active B62 deploy/rollback served-version reads use the canonical CLI."""

from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "b62-production-code-deploy-gate.yml"
CLI = ROOT / ".github" / "scripts" / "cloudflare_served_version_cli.py"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _step(job: str, name: str) -> str:
    steps = _workflow()["jobs"][job]["steps"]
    matches = [step["run"] for step in steps if step.get("name") == name]
    assert len(matches) == 1
    return matches[0]


def test_all_active_served_version_resolution_points_use_canonical_cli() -> None:
    cases = [
        ("cloudflare-readonly", "Read-only deployed state audit", 1),
        ("deploy-production-code", "Snapshot live settings immediately before mutation", 1),
        ("deploy-production-code", "Read back exact post-deploy binding and variable state", 1),
        ("deploy-production-code", "Auto-rollback to recorded version on any failed step", 2),
        ("rollback-production-code", "Roll out recorded version", 1),
    ]
    for job, name, expected_count in cases:
        run = _step(job, name)
        assert run.count("cloudflare_served_version_cli.py resolve-active") == expected_count
        assert ".result.deployments[0].versions[0].version_id" not in run
        assert ".result.deployments[0].versions[0].percentage" not in run
    assert CLI.is_file()


def test_polling_steps_retry_canonical_nonconvergence_without_widening_the_budget() -> None:
    for job, name in (
        ("deploy-production-code", "Read back exact post-deploy binding and variable state"),
        ("deploy-production-code", "Auto-rollback to recorded version on any failed step"),
        ("rollback-production-code", "Roll out recorded version"),
    ):
        run = _step(job, name)
        assert "for attempt in $(seq 1 12)" in run
        assert 'if ! active="$(python3 .github/scripts/cloudflare_served_version_cli.py resolve-active' in run
        assert 'active=""' in run
        assert "sleep 5" in run


def test_pre_mutation_reads_fail_closed_instead_of_suppressing_resolver_failure() -> None:
    for job, name in (
        ("cloudflare-readonly", "Read-only deployed state audit"),
        ("deploy-production-code", "Snapshot live settings immediately before mutation"),
    ):
        run = _step(job, name)
        assert 'active="$(python3 .github/scripts/cloudflare_served_version_cli.py resolve-active' in run
        assert 'if ! active=' not in run

    auto = _step("deploy-production-code", "Auto-rollback to recorded version on any failed step")
    precheck = auto.split("for attempt in $(seq 1 12)", 1)[0]
    assert 'active="$(python3 .github/scripts/cloudflare_served_version_cli.py resolve-active' in precheck
    assert 'if ! active=' not in precheck


def test_workflow_retriggers_when_generic_cli_changes() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    trigger_paths = text.split("on:", 1)[1].split("workflow_dispatch:", 1)[0]
    assert ".github/scripts/cloudflare_served_version_cli.py" in trigger_paths
