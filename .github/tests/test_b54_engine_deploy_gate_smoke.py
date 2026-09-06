"""Contract tests for the B54 engine deploy gate smoke-idempotency job (WO-8 PR-B).

Proves statically that the deploy gate:
  1. grew a smoke-idempotency job that needs deploy-production-engine and runs
     only on the exact deploy confirmation phrase;
  2. runs in the production environment with a bounded timeout;
  3. references the smoke caller secrets BY NAME only (values never appear);
  4. checks out the exact target SHA without persisted credentials;
  5. fails honestly when smoke secrets are missing (SKIPPED_MISSING_SECRET);
  6. runs the A9 smoke script and requires the A9_SMOKE=PASS line;
  7. does not alter the existing deploy or rollback jobs.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "b54-engine-production-deploy-gate.yml"
SMOKE_SCRIPT = ROOT / "apps" / "padiem-ai-engine" / "scripts" / "a9_production_smoke.py"


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _workflow() -> dict:
    # YAML 1.1 parses bare `on:` as True; normalise the key for portability.
    data = yaml.safe_load(_workflow_text())
    trigger = data.get("on", data.get(True))
    assert isinstance(trigger, dict)
    return {"triggers": trigger, "jobs": data["jobs"]}


def test_smoke_job_exists_and_depends_on_deploy() -> None:
    wf = _workflow()
    assert "smoke-idempotency" in wf["jobs"]
    job = wf["jobs"]["smoke-idempotency"]
    assert job["needs"] == "deploy-production-engine"
    assert job["if"] == "github.event.inputs.confirmation == 'DEPLOY_B54_ENGINE_FROM_EXACT_MAIN'"


def test_smoke_job_is_production_scoped_and_time_bounded() -> None:
    wf = _workflow()
    job = wf["jobs"]["smoke-idempotency"]
    assert job["environment"] == "production"
    assert isinstance(job["timeout-minutes"], int)
    assert 0 < job["timeout-minutes"] <= 15


def test_smoke_job_references_secret_names_not_values() -> None:
    text = _workflow_text()
    assert "secrets.PADIEM_ENGINE_SMOKE_CALLER_ID" in text
    assert "secrets.PADIEM_ENGINE_SMOKE_CALLER_SECRET" in text
    # Secret VALUES must never appear literally in the workflow.
    smoke_block = text.split("smoke-idempotency:", 1)[1].split("rollback-production-engine:", 1)[0]
    assert not re.search(r"PADIEM_ENGINE_SMOKE_[A-Z_]+:\s*(?![$\[{])[A-Za-z0-9]", smoke_block)


def test_smoke_job_checks_out_exact_sha_without_persisted_credentials() -> None:
    text = _workflow_text()
    smoke_block = text.split("smoke-idempotency:", 1)[1].split("rollback-production-engine:", 1)[0]
    assert 'ref: ${{ github.event.inputs.target_sha }}' in smoke_block
    assert "persist-credentials: false" in smoke_block


def test_smoke_job_fails_honestly_on_missing_secrets() -> None:
    text = _workflow_text()
    assert "SMOKE=SKIPPED_MISSING_SECRET" in text


def test_smoke_job_runs_the_a9_script_and_requires_the_pass_line() -> None:
    text = _workflow_text()
    smoke_block = text.split("smoke-idempotency:", 1)[1].split("rollback-production-engine:", 1)[0]
    assert "a9_production_smoke.py" in smoke_block
    assert "A9_SMOKE=PASS" in smoke_block
    assert SMOKE_SCRIPT.is_file(), "smoke script must exist in the repo"


def test_deploy_and_rollback_jobs_unchanged_in_shape() -> None:
    wf = _workflow()
    deploy = wf["jobs"]["deploy-production-engine"]
    rollback = wf["jobs"]["rollback-production-engine"]
    assert deploy["environment"] == "production"
    assert deploy["if"] == "github.event.inputs.confirmation == 'DEPLOY_B54_ENGINE_FROM_EXACT_MAIN'"
    assert rollback["if"] == "github.event.inputs.confirmation == 'ROLLBACK_B54_ENGINE_TO_PREVIOUS_VERSION'"
    assert any(step.get("name") == "Post-deploy smoke" for step in deploy["steps"])


def test_smoke_script_final_line_contract() -> None:
    """The smoke script's success line must carry the exact blocker verdicts."""
    source = SMOKE_SCRIPT.read_text(encoding="utf-8")
    assert "A9_SMOKE=PASS" in source
    assert "BLOCKER_4=PASS" in source
    assert "BLOCKER_5=PASS" in source
    assert "BLOCKER_6=PASS" in source
    assert "BLOCKER_7=PASS" in source
    assert "REAL_PROVIDER_CALLS=" in source
    assert "SKIPPED_MISSING_SECRET" in source
