"""#3703: Local Agent public-ingress gate reuses canonical served-version CLI."""

from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "b54-local-agent-public-ingress-gate.yml"
CLI = ROOT / ".github" / "scripts" / "cloudflare_served_version_cli.py"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _step(job: str, name: str) -> str:
    steps = _workflow()["jobs"][job]["steps"]
    matches = [step["run"] for step in steps if step.get("name") == name]
    assert len(matches) == 1
    return matches[0]


def test_readonly_worker_loop_uses_canonical_cli_and_exact_expected_versions() -> None:
    run = _step(
        "cloudflare-readonly",
        "Reconfirm deployed versions, private boundary, service binding and candidate domain",
    )
    assert run.count("cloudflare_served_version_cli.py resolve-active") == 1
    assert 'test "${active_version}" = "${EXPECTED_STATE_VERSION}"' in run
    assert 'test "${active_version}" = "${EXPECTED_EDGE_VERSION}"' in run
    assert ".result.deployments[0].versions[0].version_id" not in run
    assert ".result.deployments[0].versions[0].percentage" not in run


def test_premutation_recheck_uses_canonical_cli_for_both_workers() -> None:
    run = _step(
        "activate-custom-domain",
        "Fail-closed recheck immediately before Custom Domain attach",
    )
    assert run.count("cloudflare_served_version_cli.py resolve-active") == 2
    assert 'test "${state_active}" = "${EXPECTED_STATE_VERSION}"' in run
    assert 'test "${edge_active}" = "${EXPECTED_EDGE_VERSION}"' in run
    assert "PREMUTATION_PRIVATE_BOUNDARY=PASS" in run
    assert ".result.deployments[0].versions[0].version_id" not in run
    assert ".result.deployments[0].versions[0].percentage" not in run


def test_pr_merge_cannot_run_cloudflare_or_mutation_jobs() -> None:
    wf = _workflow()
    assert "pull_request" in wf[True]
    assert "workflow_dispatch" in wf[True]
    assert wf["jobs"]["cloudflare-readonly"]["if"] == "${{ github.event_name == 'workflow_dispatch' && inputs.mode != 'repository_preflight' }}"
    assert wf["jobs"]["activate-custom-domain"]["if"] == "${{ github.event_name == 'workflow_dispatch' && inputs.mode == 'activate_custom_domain' }}"
    assert wf["jobs"]["rollback-custom-domain"]["if"] == "${{ github.event_name == 'workflow_dispatch' && inputs.mode == 'rollback_custom_domain' }}"


def test_cli_change_retriggers_source_contract() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    pull_paths = text.split("pull_request:", 1)[1].split("workflow_dispatch:", 1)[0]
    assert ".github/scripts/cloudflare_served_version_cli.py" in pull_paths
    assert ".github/tests/test_3703_local_agent_public_served_version.py" in pull_paths
    assert CLI.is_file()
