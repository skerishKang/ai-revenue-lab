"""#3663: B62 Claw live-config served-version reads reuse canonical parsers."""

from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "b62-claw-live-config-activation-gate.yml"
CLI = ROOT / ".github" / "scripts" / "cloudflare_served_version_cli.py"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _step(name: str) -> str:
    matches: list[str] = []
    for job in _workflow()["jobs"].values():
        for step in job.get("steps", []):
            if step.get("name") == name:
                matches.append(step["run"])
    assert len(matches) == 1
    return matches[0]


def test_premutation_and_rollback_anchor_reads_use_generic_cli() -> None:
    for name in (
        "Record rollback anchor and pre-mutation settings snapshot",
        "Record pre-mutation settings and served version",
        "Restore the recorded pre-activation code version (CODE_VERSION_ROLLBACK)",
    ):
        run = _step(name)
        assert "cloudflare_served_version_cli.py resolve-active" in run
        assert ".result.deployments[0].versions[0]" not in run
    assert CLI.is_file()


def test_secret_replacement_poll_uses_existing_specialized_canonical_helper_only() -> None:
    run = _step("Record post-mutation served version evidence")
    assert "for attempt in $(seq 1 30)" in run
    assert "sleep 2" in run
    assert "replacement-served-version-read" in run
    assert "replacement-served-version-final" in run
    assert ".result.deployments[0].versions[0]" not in run
    assert "jq -e" not in run


def test_rollback_readback_retries_noncanonical_intermediate_state_with_same_budget() -> None:
    run = _step("Read back the restored active code version")
    assert "for _ in $(seq 1 30)" in run
    assert "sleep 2" in run
    assert "cloudflare_served_version_cli.py resolve-active" in run
    assert '&& [ "${active}" = "${ROLLBACK_VERSION_ID}" ]' in run
    assert ".result.deployments[0].versions[0]" not in run


def test_workflow_retriggers_when_generic_cli_changes() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    trigger_paths = text.split("on:", 1)[1].split("workflow_dispatch:", 1)[0]
    assert ".github/scripts/cloudflare_served_version_cli.py" in trigger_paths
