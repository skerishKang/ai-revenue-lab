"""#3709: B62 Google OAuth state binding mutation reads use the canonical CLI."""

from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "b62-google-oauth-state-binding-gate.yml"
CLI = ROOT / ".github" / "scripts" / "cloudflare_served_version_cli.py"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _step(job: str, name: str) -> str:
    steps = _workflow()["jobs"][job]["steps"]
    matches = [step["run"] for step in steps if step.get("name") == name]
    assert len(matches) == 1
    return matches[0]


def test_activation_and_rollback_premutation_reads_fail_closed_through_cli() -> None:
    for job, name in (
        ("activate-google-oauth-state-binding", "Capture exact pre-mutation Worker state"),
        ("rollback-google-oauth-state-binding", "Capture exact pre-rollback Worker state"),
    ):
        run = _step(job, name)
        assert run.count("cloudflare_served_version_cli.py resolve-active") == 1
        assert 'active="$(python3 .github/scripts/cloudflare_served_version_cli.py resolve-active' in run
        assert 'if ! active=' not in run
        assert 'test "${active}" = "${latest}"' in run
        assert ".result.deployments[0].versions[0].version_id" not in run
        assert ".result.deployments[0].versions[0].percentage" not in run


def test_postmutation_and_rollback_polls_keep_30x2s_budget() -> None:
    for job, name in (
        ("activate-google-oauth-state-binding", "Read back exact post-mutation state"),
        ("rollback-google-oauth-state-binding", "Read back rollback exactness"),
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


def test_readonly_job_keeps_existing_python_resolver_authority() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    readonly = text.split("\n  cloudflare-readonly:", 1)[1].split(
        "\n  activate-google-oauth-state-binding:", 1
    )[0]
    assert "from cloudflare_served_version import" in readonly
    assert "resolve_served_version_id" in readonly
    assert "cloudflare_served_version_cli.py resolve-active" not in readonly


def test_binding_and_source_invariants_are_preserved() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for token in (
        "LATEST_VERSION_EQUALS_ACTIVE_VERSION=PASS",
        "EXISTING_BINDINGS_UNCHANGED=PASS",
        "SOURCE_ETAG_UNCHANGED=PASS",
        "PUBLIC_TOPOLOGY_UNCHANGED=PASS",
        "SECRET_BINDING_VALUE_READ_OR_REWRITTEN=NO",
        "ROLLBACK_SECRET_BINDING_VALUE_READ_OR_REWRITTEN=NO",
    ):
        assert token in text


def test_mutation_remains_manual_dispatch_only() -> None:
    wf = _workflow()
    assert wf["jobs"]["activate-google-oauth-state-binding"]["if"] == "${{ github.event_name == 'workflow_dispatch' && inputs.mode == 'activate_google_oauth_state_binding' }}"
    assert wf["jobs"]["rollback-google-oauth-state-binding"]["if"] == "${{ github.event_name == 'workflow_dispatch' && inputs.mode == 'rollback_google_oauth_state_binding' }}"


def test_cli_and_regression_test_retrigger_source_contract() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    paths = text.split("on:", 1)[1].split("workflow_dispatch:", 1)[0]
    assert ".github/scripts/cloudflare_served_version.py" in paths
    assert ".github/scripts/cloudflare_served_version_cli.py" in paths
    assert ".github/tests/test_3709_b62_google_oauth_served_version_cli_adoption.py" in paths
    assert CLI.is_file()
