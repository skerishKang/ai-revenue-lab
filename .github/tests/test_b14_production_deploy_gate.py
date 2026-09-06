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

import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
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


def _embedded_version_check_script() -> str:
    """Extract the python heredoc that validates deployments list output."""
    text = _workflow_text()
    match = re.search(
        r"python3 - \"\$VERSION_ID\" <<'PY'\n(.*?)\n\s*PY\n",
        text,
        re.DOTALL,
    )
    assert match, "version-check heredoc not found in gate workflow"
    return textwrap.dedent(match.group(1))


def _run_version_check(tmp_path, payload, expected: str) -> subprocess.CompletedProcess:
    script = _embedded_version_check_script()
    json_file = tmp_path / "deployments.json"
    json_file.write_text(json.dumps(payload), encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-c", script, expected],
        capture_output=True,
        text=True,
        env={**os.environ, "B14_DEPLOYMENTS_JSON": str(json_file)},
    )


def test_version_check_accepts_wrangler_list_shape(tmp_path) -> None:
    # Regression (post-#1961 first dispatch): wrangler deployments list --json
    # returns a bare LIST, not {"deployments": [...]}. The first gated deploy
    # crashed the verification step with AttributeError on payload.get.
    payload = [
        {
            "version": {"id": "e1d672e7-0000-0000-0000-000000000000"},
            "strategy": {"percentage": 100},
        },
        {
            "version": {"id": "older-version"},
            "strategy": {"percentage": 0},
        },
    ]
    result = _run_version_check(tmp_path, payload, "e1d672e7-0000-0000-0000-000000000000")
    assert result.returncode == 0, result.stderr
    assert "POST_DEPLOY_VERSION_AT_100=PASS" in result.stdout


def test_version_check_accepts_object_shape(tmp_path) -> None:
    payload = {
        "deployments": [
            {
                "version": {"id": "abc123"},
                "strategy": {"percentage": 100},
            }
        ]
    }
    result = _run_version_check(tmp_path, payload, "abc123")
    assert result.returncode == 0, result.stderr
    assert "POST_DEPLOY_VERSION_AT_100=PASS" in result.stdout


def test_version_check_still_fails_on_version_mismatch_or_partial_rollout(tmp_path) -> None:
    mismatch = _run_version_check(
        tmp_path,
        [{"version": {"id": "other"}, "strategy": {"percentage": 100}}],
        "expected-id",
    )
    assert mismatch.returncode != 0

    not_full = _run_version_check(
        tmp_path,
        [{"version": {"id": "expected-id"}, "strategy": {"percentage": 50}}],
        "expected-id",
    )
    assert not_full.returncode != 0


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
