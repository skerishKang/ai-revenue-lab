"""#3706: authoritative Local Agent activation gate uses canonical served-version CLI."""

from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "b54-local-agent-public-ingress-activation.yml"
CLI = ROOT / ".github" / "scripts" / "cloudflare_served_version_cli.py"
STATE_PIN = "b5b5e0f1-96de-4521-8242-86466b4b1803"
EDGE_PIN = "c2217fb5-3a63-4fd5-90d9-431bd94c4a97"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _step(job: str, name: str) -> str:
    steps = _workflow()["jobs"][job]["steps"]
    matches = [step["run"] for step in steps if step.get("name") == name]
    assert len(matches) == 1
    return matches[0]


def test_runbook_version_pins_are_unchanged() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert f"EXPECTED_STATE_VERSION: {STATE_PIN}" in text
    assert f"EXPECTED_EDGE_VERSION: {EDGE_PIN}" in text


def test_preflight_uses_one_canonical_lookup_per_worker_iteration() -> None:
    run = _step(
        "preflight-verification",
        "Inspect current versions, boundary, service binding and Custom Domain",
    )
    assert run.count("cloudflare_served_version_cli.py resolve-active") == 1
    assert 'test "${active_version}" = "${EXPECTED_STATE_VERSION}"' in run
    assert 'test "${active_version}" = "${EXPECTED_EDGE_VERSION}"' in run
    assert ".result.deployments[0].versions[0]" not in run


def test_premutation_and_postactivation_preserve_exact_pins() -> None:
    for name in (
        "Fail-closed recheck immediately before mutation",
        "Read back exact public boundary and run bounded unauthenticated HTTPS smoke",
    ):
        run = _step("activate-public-ingress", name)
        assert run.count("cloudflare_served_version_cli.py resolve-active") == 2
        assert 'test "${state_active}" = "${EXPECTED_STATE_VERSION}"' in run
        assert 'test "${edge_active}" = "${EXPECTED_EDGE_VERSION}"' in run
        assert ".result.deployments[0].versions[0]" not in run
    readback = _step(
        "activate-public-ingress",
        "Read back exact public boundary and run bounded unauthenticated HTTPS smoke",
    )
    assert "VERSIONS_PRESERVED=PASS" in readback
    assert "for _ in $(seq 1 60)" in readback


def test_rollback_preserves_pins_and_existing_poll_budget() -> None:
    run = _step("rollback-remove-custom-domain", "Detach only the exact Custom Domain")
    assert run.count("cloudflare_served_version_cli.py resolve-active") == 2
    assert 'test "${state_active}" = "${EXPECTED_STATE_VERSION}"' in run
    assert 'test "${edge_active}" = "${EXPECTED_EDGE_VERSION}"' in run
    assert "for _ in $(seq 1 30)" in run
    assert "sleep 2" in run
    assert "WORKER_REDEPLOY=NO" in run
    assert "VERSIONS_PRESERVED=PASS" in run
    assert ".result.deployments[0].versions[0]" not in run


def test_pr_merge_is_source_only_and_mutation_remains_manual_dispatch() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "\npush:" not in text
    wf = _workflow()
    assert wf["jobs"]["preflight-verification"]["if"] == "${{ github.event_name == 'workflow_dispatch' }}"
    assert wf["jobs"]["activate-public-ingress"]["if"] == "${{ github.event_name == 'workflow_dispatch' && inputs.mode == 'activate_public_ingress' }}"
    assert wf["jobs"]["rollback-remove-custom-domain"]["if"] == "${{ github.event_name == 'workflow_dispatch' && inputs.mode == 'rollback_remove_custom_domain' }}"


def test_cli_and_regression_test_retrigger_source_contract() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    pull_paths = text.split("pull_request:", 1)[1].split("workflow_dispatch:", 1)[0]
    assert ".github/scripts/cloudflare_served_version_cli.py" in pull_paths
    assert ".github/tests/test_3706_local_agent_activation_served_version.py" in pull_paths
    runtime = text.split("\n  preflight-verification:", 1)[1]
    assert runtime.count("cloudflare_served_version_cli.py resolve-active") == 7
    assert CLI.is_file()
