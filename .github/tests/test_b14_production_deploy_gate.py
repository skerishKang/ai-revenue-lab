"""Contract tests for the B14 production deploy gate workflow (#1955).

Proves statically that the gate:
  1. is dispatch-only (a pull request can never trigger a production mutation);
  2. carries the exact-SHA + account premutation assertions, fail-closed;
  3. deploys via the repository's canonical pipeline (bash ./deploy.sh);
  4. verifies post-deploy version-at-100 + engine b14_service_bound smoke;
  5. exposes a separately-confirmed rollback job;
and that deploy.sh itself remains syntactically valid (bash -n).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "b14-production-deploy-gate.yml"
DEPLOY_SH = ROOT / "apps" / "korean-ai-platform" / "deploy.sh"


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _workflow() -> dict:
    # YAML 1.1 parses bare `on:` as True; normalise the key for portability.
    data = yaml.safe_load(_workflow_text())
    trigger = data.get("on", data.get(True))
    assert isinstance(trigger, dict)
    return {"triggers": trigger, "jobs": data["jobs"]}


def test_workflow_parses_and_is_dispatch_only() -> None:
    wf = _workflow()
    assert set(wf["triggers"]) == {"workflow_dispatch"}, (
        "gate must be workflow_dispatch-only: an ordinary pull request must "
        "never trigger a production mutation"
    )
    inputs = wf["triggers"]["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"target_sha", "confirmation"}
    for spec in inputs.values():
        assert spec["required"] is True


def test_deploy_job_requires_exact_confirmation_phrase() -> None:
    wf = _workflow()
    deploy = wf["jobs"]["deploy-production-b14"]
    assert deploy["if"] == "github.event.inputs.confirmation == 'DEPLOY_B14_FROM_EXACT_MAIN'"
    assert deploy["environment"] == "production"


def test_premutation_assertions_are_fail_closed_and_non_interactive() -> None:
    text = _workflow_text()
    assert "set -euo pipefail" in text
    # HEAD == TARGET_SHA, origin/main == TARGET_SHA, account id pinned.
    assert re.search(r'test "\$\(git rev-parse HEAD\)" = "\$\{\{ github\.event\.inputs\.target_sha \}\}"', text)
    assert re.search(r'test "\$\(git rev-parse origin/main\)" = "\$\{\{ github\.event\.inputs\.target_sha \}\}"', text)
    assert "9be14bb7b8974e65d0afba647ab16932" in text
    # No interactive constructs in the gate.
    assert "workflow_dispatch" in text
    for forbidden in ("Read-Host", "prompt", "--interactive"):
        assert forbidden not in text


def test_deploy_step_uses_canonical_pipeline() -> None:
    text = _workflow_text()
    assert "bash ./deploy.sh" in text, (
        "the gate must run the repository's canonical deploy.sh, not a "
        "duplicated build pipeline"
    )
    # No duplicated canonical steps in the workflow itself
    # (deployments list / rollback are verification-recovery commands, not deploys).
    assert "pywrangler sync" not in text
    assert not re.search(r"npx wrangler@\d+ deploy(?!ments)", text)


def test_post_deploy_verification_is_blocking() -> None:
    text = _workflow_text()
    assert "Current Version ID" in text
    assert "deployments list" in text
    assert "POST_DEPLOY_VERSION_AT_100=PASS" in text
    assert '"b14_service_bound":true' in text
    assert "ENGINE_B14_BOUND_SMOKE=PASS" in text
    assert "B14_KILO_CATALOG_MARKER=PASS" in text
    # Verification runs inside the deploy job (needs: semantics via same job).
    deploy = _workflow()["jobs"]["deploy-production-b14"]
    step_names = [step.get("name", "") for step in deploy["steps"]]
    assert any("Post-deploy verification" in name for name in step_names)


def test_rollback_job_is_separately_confirmed() -> None:
    wf = _workflow()
    rollback = wf["jobs"]["rollback-production-b14"]
    assert rollback["if"] == "github.event.inputs.confirmation == 'ROLLBACK_B14_TO_PREVIOUS_VERSION'"
    assert rollback["environment"] == "production"
    text = _workflow_text()
    assert "npx wrangler@4 rollback" in text


def test_deploy_sh_is_syntactically_valid() -> None:
    # CI (ubuntu) always has /bin/bash. Locally on Windows, resolve Git Bash
    # explicitly because subprocess does not go through the shell's PATH.
    bash = shutil.which("bash")
    if bash is None:
        git = shutil.which("git")
        if git is not None:
            candidate = Path(git).resolve().parents[2] / "bin" / "bash.exe"
            bash = str(candidate) if candidate.exists() else None
    if bash is None:
        raise AssertionError("bash not found; contract requires bash -n on deploy.sh")
    subprocess.run(
        [bash, "-n", str(DEPLOY_SH)],
        check=True,
        capture_output=True,
    )
