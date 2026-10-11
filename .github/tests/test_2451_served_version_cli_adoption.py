"""#3656 contract: Engine deploy CP-admission reuses canonical served-version rules."""

from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "b54-engine-production-deploy-gate.yml"
CLI = ROOT / ".github" / "scripts" / "cloudflare_served_version_cli.py"


def _workflow() -> dict:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return data


def _target_run() -> str:
    steps = _workflow()["jobs"]["deploy-production-engine"]["steps"]
    matches = [
        step["run"]
        for step in steps
        if step.get("name") == "Pre-deploy A7 Control Plane admission readiness"
    ]
    assert len(matches) == 1
    return matches[0]


def test_cp_admission_uses_generic_canonical_resolver_cli() -> None:
    run = _target_run()
    assert (
        'python3 .github/scripts/cloudflare_served_version_cli.py resolve-active --deployments "${deployments}"'
        in run
    )
    assert "CP_ADMISSION_SERVED_VERSION_RESOLVER=CANONICAL" in run
    assert CLI.is_file()


def test_cp_admission_no_longer_reimplements_served_version_shape_with_jq() -> None:
    run = _target_run()
    for forbidden in (
        ".result.deployments[0].versions[0].version_id",
        ".result.deployments[0].versions[0].percentage",
        ".result.deployments[0].versions | length",
    ):
        assert forbidden not in run


def test_cp_admission_keeps_other_readiness_checks_and_no_mutation() -> None:
    run = _target_run()
    assert '".result.bindings"' not in run  # YAML jq expressions are single-quoted text.
    assert ".result.bindings" in run
    assert "CONTROL_PLANE_IDENTITY" in run
    assert ".result.enabled == false" in run
    assert "curl -fsS" in run
    assert "-X POST" not in run
    assert "-X PUT" not in run
    assert "-X DELETE" not in run
