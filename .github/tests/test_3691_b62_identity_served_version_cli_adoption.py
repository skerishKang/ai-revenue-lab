"""#3691: B62 identity binding mutation reads reuse canonical served-version CLI."""

from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "b62-control-plane-identity-binding-gate.yml"
CLI = ROOT / ".github" / "scripts" / "cloudflare_served_version_cli.py"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _step(job: str, name: str) -> str:
    steps = _workflow()["jobs"][job]["steps"]
    matches = [step["run"] for step in steps if step.get("name") == name]
    assert len(matches) == 1
    return matches[0]


def test_activation_and_rollback_pre_reads_fail_closed_through_canonical_cli() -> None:
    for job, name in (
        ("activate-identity-binding", "Capture exact pre-mutation Worker state"),
        ("rollback-identity-binding", "Capture exact pre-rollback Worker state"),
    ):
        run = _step(job, name)
        assert run.count("cloudflare_served_version_cli.py resolve-active") == 1
        assert 'active="$(python3 .github/scripts/cloudflare_served_version_cli.py resolve-active' in run
        assert 'if ! active=' not in run
        assert 'test "${active}" = "${latest}"' in run
        assert ".result.deployments[0].versions[0].version_id" not in run
        assert ".result.deployments[0].versions[0].percentage" not in run


def test_activation_and_rollback_polls_preserve_30x2s_budget_and_retry_nonconvergence() -> None:
    for job, name in (
        ("activate-identity-binding", "Read back exact post-mutation state"),
        ("rollback-identity-binding", "Read back rollback exactness"),
    ):
        run = _step(job, name)
        assert "for _ in $(seq 1 30)" in run
        assert "sleep 2" in run
        assert run.count("cloudflare_served_version_cli.py resolve-active") == 1
        assert 'if ! active="$(python3 .github/scripts/cloudflare_served_version_cli.py resolve-active' in run
        assert 'active=""' in run
        assert '[ "${active}" != "${BEFORE_VERSION}" ]' in run
        assert ".result.deployments[0].versions[0].version_id" not in run
        assert ".result.deployments[0].versions[0].percentage" not in run


def test_readonly_keeps_existing_python_resolver_authority() -> None:
    run = "\n".join(
        step.get("run", "")
        for step in _workflow()["jobs"]["cloudflare-readonly"]["steps"]
        if "run" in step
    )
    assert "from cloudflare_served_version import" in run
    assert "resolve_served_version_id" in run
    assert "cloudflare_served_version_cli.py resolve-active" not in run


def test_cli_is_in_trigger_paths_without_removing_existing_resolver_paths() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    trigger_paths = text.split("on:", 1)[1].split("workflow_dispatch:", 1)[0]
    assert ".github/scripts/cloudflare_served_version.py" in trigger_paths
    assert ".github/scripts/cloudflare_served_version_cli.py" in trigger_paths
    assert ".github/tests/test_cloudflare_served_version.py" in trigger_paths
    assert CLI.is_file()
