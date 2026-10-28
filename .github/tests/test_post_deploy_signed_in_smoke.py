"""#5895 follow-up: the deploy gate must answer as a signed-in owner, not only as a visitor.

On 2026-10-28 a released Chat build served every anonymous path correctly while
each path that reads a session answered 500, and the gate's existing free-composer
proof went green on it. These checks are about the judgement and the placement of
the new proof - not the network:

  * a walk whose session reads all answer 200 passes;
  * the incident itself - a session read that answers 500 - fails, and the step
    that failed is named, because that is the whole difference between a red gate
    and a two-hour outage nobody was told about;
  * a session that does not report itself authenticated fails even when every
    status line was 200;
  * only the model-side lane keeps its 429/503 excuse, and only as a marked pass;
  * the step runs after the auto-rollback step and carries no ``if:`` of its own,
    so a failed proof is read by a person and never rolls a release by itself;
  * the QA identity is consumed by NAME only, as the existing proofs do.
"""
from __future__ import annotations
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / ".github/scripts"
WORKFLOW = ROOT / ".github/workflows/b62-production-code-deploy-gate.yml"
STEP_NAME = "Post-deploy signed-in session check"
ROLLBACK_STEP = "Auto-rollback to recorded version on any failed step"
EXISTING_STEP = "Post-deploy real chat"

sys.path.insert(0, str(SCRIPTS))

from post_deploy_signed_in_smoke import (  # noqa: E402
    STEP_ORDER,
    decide_path,
)

SIGNED_IN_WALK = [
    ("login", 200, {"ok": True}),
    ("auth_status", 200, {"authenticated": True, "user": {"email": "qa@example.test"}}),
    ("conversations", 200, {"conversations": []}),
    ("chat", 200, {"answer": "네, 정상입니다.", "conversation_id": "chat_" + "a" * 32}),
]


def _steps() -> list[dict]:
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    return jobs["deploy-production-code"]["steps"]


def _names(steps: list[dict]) -> list[str]:
    return [str(step.get("name", "")) for step in steps]


def test_a_signed_in_walk_that_answers_is_a_pass() -> None:
    assert [step for step, _, _ in SIGNED_IN_WALK] == list(STEP_ORDER)
    assert decide_path(SIGNED_IN_WALK) == ("PASS", "none")


def test_the_incident_shape_fails_and_names_the_session_read_that_broke() -> None:
    """Every session path answered 500 while the free composer kept working."""
    incident = [
        ("login", 200, {"ok": True}),
        ("auth_status", 500, None),
        ("conversations", 500, None),
        ("chat", 500, None),
    ]
    verdict, code = decide_path(incident)
    assert verdict == "FAIL"
    assert code == "auth_status:http_500", code

    # The walk stops at the first broken step, and a missing step is itself a
    # failure: a proof that never reached the conversation list proved nothing.
    assert decide_path(SIGNED_IN_WALK[:2]) == ("FAIL", "missing_step_conversations")
    # A 200 that says "not signed in" is a failure too - the session cookie is
    # the thing under test, not the HTTP layer.
    guest = list(SIGNED_IN_WALK)
    guest[1] = ("auth_status", 200, {"authenticated": False, "session_state": "guest"})
    assert decide_path(guest) == ("FAIL", "auth_status:session_not_authenticated")
    # A history read shaped like nothing the browser can list is a failure even
    # at 200, and a provider-side limit excuses only the model turn.
    unshape = list(SIGNED_IN_WALK)
    unshape[2] = ("conversations", 200, {"detail": "not found"})
    assert decide_path(unshape) == ("FAIL", "conversations:conversations_list_unreadable")
    limited = list(SIGNED_IN_WALK)
    limited[3] = ("chat", 503, {"error": {"code": "rate_limited"}})
    assert decide_path(limited)[0] == "PASS_PROVIDER_LIMIT"


def test_the_proof_runs_after_the_rollback_and_is_never_conditional() -> None:
    steps = _steps()
    names = _names(steps)
    assert STEP_NAME in names, names
    # The old anonymous proof stays exactly where it was: this is an added
    # reading, not a replacement of the lane that already existed.
    assert EXISTING_STEP in names and names.index(EXISTING_STEP) < names.index(STEP_NAME)
    assert names.index(ROLLBACK_STEP) < names.index(STEP_NAME)
    step = next(item for item in steps if item.get("name") == STEP_NAME)
    assert "if" not in step, step
    body = str(step.get("run", ""))
    assert "post_deploy_signed_in_smoke.py" in body
    # The QA identity is named, never valued: the gate carries no credential text.
    env = step.get("env") or {}
    assert env["B66_CGI_ALPHA_USERNAME"].startswith("${{ vars."), env
    assert env["B66_CGI_ALPHA_PASSWORD"].startswith("${{ secrets."), env
    assert "${{" not in body
