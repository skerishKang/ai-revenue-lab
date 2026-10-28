"""#5895 follow-up: a rollback must not be gated by the baseline of the version it leaves.

On 2026-10-28 Chat was answering 500 for every signed-in path and the gate's own
``rollback_production_code`` mode refused to run: its read-only pre-step compared
the live binding set with the reviewed deploy baseline, reported
``BINDING_SET_DRIFT``, and exited non-zero - while the only thing that could have
made the comparison match was the rollback itself. The CTO rolled the Worker back
to ``2fb11b2b-606c-44c8-a5ff-d66c6b53dc53`` by hand with ``wrangler rollback`` at
11:50.

These checks run the rollback branch of that step as shell, against a stubbed
baseline comparison, and assert what a reader should see: a drifted leaving
version is noted and the job continues, a matching one is confirmed, and the step
still mutates nothing. What a rollback still has to prove - that the target
exists and is a recorded version - lives in the rollback job and is checked here
by presence, because relaxing the wrong thing is how an outage turns into a
release of the same broken version.
"""
from __future__ import annotations
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/b62-production-code-deploy-gate.yml"
READONLY_JOB = "cloudflare-readonly"
BASELINE_STEP = "Prove the live binding set matches the reviewed baseline"
ROLLBACK_MODE = "rollback_production_code"
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(BASH is None, reason="bash is required to run the step body")


def _steps(job: str) -> list[dict]:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"][job]["steps"]


def _rollback_branch() -> str:
    step = next(item for item in _steps(READONLY_JOB) if item.get("name") == BASELINE_STEP)
    body = str(step.get("run", ""))
    lines = body.splitlines()
    start = next(index for index, line in enumerate(lines)
                 if line.strip().startswith("if [") and ROLLBACK_MODE in line)
    depth, collected = 0, []
    for line in lines[start:]:
        stripped = line.strip()
        if stripped.startswith("if "):
            depth += 1
        if stripped == "fi":
            depth -= 1
        collected.append(line)
        if depth == 0:
            break
    return "\n".join(collected)


def _run_branch(tmp_path: Path, *, drift: bool) -> subprocess.CompletedProcess:
    """Execute the rollback branch with the baseline comparison stubbed."""
    stubs = tmp_path / "stubs"
    stubs.mkdir(parents=True)
    exit_code = 2 if drift else 0
    (stubs / "python3").write_text(f"#!/bin/sh\nexit {exit_code}\n", encoding="utf-8")
    os.chmod(stubs / "python3", 0o755)
    payload = tmp_path / "served.json"
    payload.write_text("{}", encoding="utf-8")
    script = tmp_path / "branch.sh"
    script.write_text(textwrap.dedent(f"""
        #!/usr/bin/env bash
        set -euo pipefail
        B62_WORKER=padiem-chat
        RUNNER_TEMP="{tmp_path}"
        chat_served="{payload}"
        chat_settings="{payload}"
        """) + _rollback_branch().replace("${{ inputs.mode }}", ROLLBACK_MODE) + "\n",
        encoding="utf-8")
    env = dict(os.environ, PATH=f"{stubs}{os.pathsep}{os.environ['PATH']}")
    return subprocess.run([BASH, str(script)], capture_output=True, text=True,
                          timeout=120, env=env, encoding="utf-8", errors="replace")


def test_a_rolled_back_version_is_not_blocked_by_the_baseline_it_is_leaving(tmp_path) -> None:
    branch = _rollback_branch()
    assert "b62_binding_baseline.py" in branch
    # The comparison is asked, and its answer is reported - it is not the gate.
    assert "if python3 .github/scripts/b62_binding_baseline.py" in branch

    drift = _run_branch(tmp_path / "drift", drift=True)
    assert drift.returncode == 0, drift.stdout + drift.stderr
    assert "B62_ROLLBACK_LEAVING_VERSION_BINDINGS=RESIDUE_NOTED" in drift.stdout
    assert "PRODUCTION_MUTATION=0" in drift.stdout

    matching = _run_branch(tmp_path / "match", drift=False)
    assert matching.returncode == 0, matching.stdout + matching.stderr
    assert "B62_ROLLBACK_LEAVING_VERSION_BINDINGS=MATCHES_BASELINE" in matching.stdout


def test_the_rollback_still_proves_the_target_is_a_recorded_version() -> None:
    """What stayed hard, in the job that performs the rollback."""
    steps = _steps("rollback-production-code")
    names = [str(step.get("name", "")) for step in steps]
    assert "Require explicit rollback authorization" in names
    assert "Locate recorded version in history" in names
    body = "\n".join(str(step.get("run", "")) for step in steps)
    # The version id comes from a person, must be non-empty, must be present in
    # the Worker's own version history, and must have a readable script artifact.
    assert 'test -n "${PREVIOUS_VERSION_ID}"' in body
    assert "/versions/" in body
    assert ".result.resources.script.etag" in body
    assert "b62_rollback_recorded_version_guard.py" in (
        WORKFLOW.read_text(encoding="utf-8"))
