"""Workflow contract for the A12 provider-independent verdict (#2786 M4-4).

Locks the gate-level contract only. It asserts that both A12 gate files accept the
SKIPPED_UPSTREAM verdict while still failing on FAIL, that the evidence line is
recorded, and that the deploy and rollback logic around the A12 step is untouched.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
DEPLOY_GATE = REPO / ".github" / "workflows" / "b54-engine-production-deploy-gate.yml"
SMOKE_ONLY_GATE = REPO / ".github" / "workflows" / "b54-engine-production-smoke-only-gate.yml"
A12_STEP_NAME = "Run A12 streaming idempotency replay smoke"


def _a12_step(path: Path) -> str:
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    for job in workflow["jobs"].values():
        for step in job.get("steps", []):
            if step.get("name") == A12_STEP_NAME:
                run = step.get("run")
                assert isinstance(run, str)
                return run
    raise AssertionError(f"{path.name} is missing the A12 step")


def _service_values(workflow: dict) -> dict[str, dict]:
    return {
        job_name: job
        for job_name, job in workflow["jobs"].items()
        if job_name != "deploy-production-engine"
    }


def test_both_gates_accept_the_skip_verdict_and_still_fail_on_fail() -> None:
    for path in (DEPLOY_GATE, SMOKE_ONLY_GATE):
        run = _a12_step(path)
        assert re.search(r"grep -qE 'A12_STREAM_REPLAY_SMOKE=\(PASS\|SKIPPED_UPSTREAM\)'", run)
        assert "grep -q 'A12_STREAM_REPLAY_SMOKE=FAIL'" in run
        assert "exit 1" in run
        assert "A12_REPLAY_EVIDENCE=" in run


def test_gates_do_not_accept_the_skip_verdict_as_a_plain_pass() -> None:
    for path in (DEPLOY_GATE, SMOKE_ONLY_GATE):
        run = _a12_step(path)
        # The verdict is recorded, not silently normalised into PASS.
        assert "A12_STREAM_REPLAY_SMOKE=PASS" not in run.replace(
            "'A12_STREAM_REPLAY_SMOKE=FAIL'", ""
        )


def test_deploy_and_rollback_sections_are_untouched() -> None:
    text = DEPLOY_GATE.read_text(encoding="utf-8")
    assert "- name: Deploy engine to production" in text
    assert "uv run pywrangler deploy" in text
    assert "rollback_version_id" in text
    # The A12 change must not carry any deploy/rollback/secret mutation with it.
    run = _a12_step(DEPLOY_GATE)
    for forbidden in ("wrangler deploy", "secret put", "pywrangler deploy", "d1 execute --remote"):
        assert forbidden not in run


def test_smoke_only_gate_remains_mutation_free() -> None:
    run = _a12_step(SMOKE_ONLY_GATE)
    for forbidden in ("pywrangler", "secret put", "rollback"):
        assert forbidden not in run
