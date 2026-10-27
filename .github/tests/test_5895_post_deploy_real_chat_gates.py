"""#5895 ④: both production gates must answer one real chat after a deploy.

The static contract is about placement and authority, not about the network:

  * the Chat gate's real-chat proof runs AFTER its ``if: failure()``
    auto-rollback step, so a failed proof reddens the gate and never rolls back;
  * the Engine gate has no failure()-based rollback at all, and none is added;
  * neither step carries an ``if:`` of its own, so it is a normal meaning of
    success rather than an optional observation;
  * both steps call the one shared script, and the Engine step consumes the
    existing QA identity by NAME only, exactly as the long-context canary does.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CHAT_GATE = ROOT / ".github/workflows/b62-production-code-deploy-gate.yml"
ENGINE_GATE = ROOT / ".github/workflows/b54-engine-production-deploy-gate.yml"
SCRIPT = ROOT / ".github/scripts/post_deploy_real_chat_smoke.py"

STEP_NAME = "Post-deploy real chat"
ROLLBACK_STEP = "Auto-rollback to recorded version on any failed step"


def _job(workflow: Path, job: str) -> dict:
    return yaml.safe_load(workflow.read_text(encoding="utf-8"))["jobs"][job]


def _steps(workflow: Path, job: str) -> list[dict]:
    return _job(workflow, job)["steps"]


def _names(steps: list[dict]) -> list[str]:
    return [str(step.get("name", "")) for step in steps]


def check_proof_is_outside_the_rollback_guard(names: list[str]) -> bool:
    """True only when the real-chat proof comes after the rollback step."""
    try:
        return names.index(ROLLBACK_STEP) < names.index(STEP_NAME)
    except ValueError:
        return False


def _step(steps: list[dict], name: str) -> dict:
    return next(step for step in steps if step.get("name") == name)


def test_the_shared_script_exists_and_is_the_single_source() -> None:
    assert SCRIPT.is_file()
    for workflow, job in ((CHAT_GATE, "deploy-production-code"), (ENGINE_GATE, "deploy-production-engine")):
        runs = [str(step.get("run", "")) for step in _steps(workflow, job)]
        # Exactly one step body invokes the script: one shared implementation,
        # no second copy of the verdict logic inside the workflow.
        assert sum(run.count(SCRIPT.name) for run in runs) == 1


def test_chat_gate_answers_one_real_chat_on_the_free_composer_lane() -> None:
    steps = _steps(CHAT_GATE, "deploy-production-code")
    step = _step(steps, STEP_NAME)
    assert step.get("if") is None
    assert "post_deploy_real_chat_smoke.py --lane chat" in step["run"]
    assert "set -euo pipefail" in step["run"]


def test_chat_gate_real_chat_proof_sits_after_the_auto_rollback_guard() -> None:
    names = _names(_steps(CHAT_GATE, "deploy-production-code"))
    assert _step(steps := _steps(CHAT_GATE, "deploy-production-code"), ROLLBACK_STEP)["if"] == "failure()"
    assert check_proof_is_outside_the_rollback_guard(names)


def test_swapping_the_proof_before_the_rollback_guard_fails_the_same_checker() -> None:
    names = _names(_steps(CHAT_GATE, "deploy-production-code"))
    guard, proof = names.index(ROLLBACK_STEP), names.index(STEP_NAME)
    names[guard], names[proof] = names[proof], names[guard]
    assert not check_proof_is_outside_the_rollback_guard(names)


def test_dropping_the_proof_fails_the_same_checker() -> None:
    names = [name for name in _names(_steps(CHAT_GATE, "deploy-production-code")) if name != STEP_NAME]
    assert not check_proof_is_outside_the_rollback_guard(names)


def test_engine_gate_answers_one_real_chat_on_the_orchestration_lane() -> None:
    steps = _steps(ENGINE_GATE, "deploy-production-engine")
    step = _step(steps, STEP_NAME)
    assert step.get("if") is None
    assert "post_deploy_real_chat_smoke.py --lane engine" in step["run"]
    assert _names(steps).index("Post-deploy smoke") < _names(steps).index(STEP_NAME)


def test_engine_gate_gains_no_failure_based_rollback() -> None:
    steps = _steps(ENGINE_GATE, "deploy-production-engine")
    assert [step.get("if") for step in steps].count("failure()") == 0
    assert "Auto-rollback" not in " ".join(_names(steps))
    # The existing rollback path stays a separate, differently confirmed job.
    rollback = _job(ENGINE_GATE, "rollback-production-engine")
    assert rollback["if"] == (
        "github.event.inputs.confirmation == 'ROLLBACK_B54_ENGINE_TO_PREVIOUS_VERSION'"
    )


def test_engine_gate_consumes_the_existing_qa_identity_by_name_only() -> None:
    # The credential is referenced, never written: the values stay in the
    # production environment the gate already runs in. These are the same two
    # names the long-context canary signs in with, so #5895 adds no secret.
    env = _step(_steps(ENGINE_GATE, "deploy-production-engine"), STEP_NAME)["env"]
    assert env["B66_CGI_ALPHA_USERNAME"] == "${{ vars.B66_CGI_ALPHA_USERNAME }}"
    assert env["B66_CGI_ALPHA_PASSWORD"] == "${{ secrets.B66_CGI_ALPHA_PASSWORD }}"
    assert set(env) == {"B66_CGI_ALPHA_USERNAME", "B66_CGI_ALPHA_PASSWORD"}
    canary = (ROOT / ".github/workflows/b62-live-long-context-canary.yml").read_text(encoding="utf-8")
    for reference in (env["B66_CGI_ALPHA_USERNAME"], env["B66_CGI_ALPHA_PASSWORD"]):
        assert f": {reference}\n" in canary
    for source in (CHAT_GATE, ENGINE_GATE):
        text = source.read_text(encoding="utf-8")
        assert not re.search(r"B66_CGI_ALPHA_(USERNAME|PASSWORD):\s*(?![$\[{])[A-Za-z0-9]", text)
