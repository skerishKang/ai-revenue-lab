"""Focused behavioral tests for the extracted orchestration wire/parse module.

These lock the #1792 R2B-2 extraction: allowed-field sets, defaults, regex
bounds, retry limits, AgentPlan/recovery parsing, cancel-reason handling,
approval-decision wire parsing, continuation-ref validation, and the exact
error taxonomy must match the pre-extraction behavior of
``app.orchestration_service``.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.orchestration_service import (
    ApprovalDecisionSubmission,
    ORCHESTRATE_CANCEL_PATH,
    ORCHESTRATE_PATH,
    ORCHESTRATE_RESUME_PATH,
    _CANCEL_ALLOWED,
    _EXEC_FIELDS,
    _ORCHESTRATE_ALLOWED,
    _RESUME_ALLOWED,
    _parse_agent_plan,
    _parse_approval_decision_submission,
    _parse_cancel_reason,
    _parse_continuation_ref,
    _parse_max_retries,
    _parse_orchestration_options,
    _parse_recovery_policy,
    _parse_subject_id,
    _required_text,
    _require_strict_bool,
)
from app.orchestration_wire import (
    _AGENT_ID_RE,
    _MAX_AGENT_STEP_RETRIES,
    _MAX_CANCEL_REASON_LEN,
    _MAX_ORCHESTRATION_RETRIES,
    _parse_max_retries_per_step,
    _parse_plan_step,
    _parse_required_timestamp,
    _parse_retryable_driver_codes,
)
from app.service import ServiceContractError


def _code(fn, *args, **kwargs) -> str:
    with pytest.raises(ServiceContractError) as excinfo:
        fn(*args, **kwargs)
    return excinfo.value.code


def _message_and_status(fn, *args, **kwargs):
    with pytest.raises(ServiceContractError) as excinfo:
        fn(*args, **kwargs)
    return excinfo.value.code, excinfo.value.safe_message, excinfo.value.status_code


# ---------------------------------------------------------------------------
# Route constants and allowed-field sets
# ---------------------------------------------------------------------------


def test_route_constants_values():
    assert ORCHESTRATE_PATH == "/internal/v1/orchestrate"
    assert ORCHESTRATE_RESUME_PATH == "/internal/v1/orchestrate/resume"
    assert ORCHESTRATE_CANCEL_PATH == "/internal/v1/orchestrate/cancel"


def test_allowed_field_sets_exact_membership():
    assert _EXEC_FIELDS == frozenset({
        "app_id", "agent", "messages", "session_id", "additional_system_context",
        "trace_id", "execution_context",
    })
    assert _ORCHESTRATE_ALLOWED == _EXEC_FIELDS | {
        "agent_plan", "recovery_policy", "max_retries", "subject_id",
        "require_evidence", "require_verification", "tool_arguments",
    }
    assert _RESUME_ALLOWED == _EXEC_FIELDS | {
        "continuation_ref", "decision", "tool_arguments",
        "agent_plan", "recovery_policy", "max_retries", "subject_id",
    }
    assert _CANCEL_ALLOWED == frozenset({"app_id", "continuation_ref", "reason"})


def test_reexport_identity_between_service_and_wire():
    import app.orchestration_service as service
    import app.orchestration_wire as wire

    for name in (
        "ORCHESTRATE_PATH", "ORCHESTRATE_RESUME_PATH", "ORCHESTRATE_CANCEL_PATH",
        "_SAFE_ID_RE", "_IDENTIFIER_RE", "_AGENT_ID_RE",
        "_MAX_ORCHESTRATION_RETRIES", "_MAX_AGENT_STEP_RETRIES", "_MAX_CANCEL_REASON_LEN",
        "_EXEC_FIELDS", "_ORCHESTRATION_OPTIONS", "_ORCHESTRATION_RESUME_OPTIONS",
        "_ORCHESTRATE_ALLOWED", "_RESUME_ALLOWED", "_CANCEL_ALLOWED",
        "_AGENT_PLAN_ALLOWED", "_PLAN_STEP_ALLOWED", "_RECOVERY_ALLOWED",
        "ApprovalDecisionSubmission",
        "_parse_max_retries", "_parse_max_retries_per_step", "_parse_subject_id",
        "_require_strict_bool", "_parse_retryable_driver_codes", "_parse_plan_step",
        "_parse_agent_plan", "_parse_recovery_policy", "_parse_cancel_reason",
        "_parse_orchestration_options", "_parse_required_timestamp", "_required_text",
        "_parse_approval_decision_submission", "_parse_continuation_ref",
    ):
        assert getattr(service, name) is getattr(wire, name), name


# ---------------------------------------------------------------------------
# max_retries
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, 3),
        (3, 3),
        (0, 0),
        (10, 10),
    ],
)
def test_parse_max_retries_valid(value, expected):
    assert _parse_max_retries(value) == expected


@pytest.mark.parametrize("value", [True, False, "3", 3.0, -1, 11, 999])
def test_parse_max_retries_rejected(value):
    assert _code(_parse_max_retries, value) == "invalid_max_retries"


def test_parse_max_retries_bounds_and_messages():
    assert _MAX_ORCHESTRATION_RETRIES == 10
    code, message, status = _message_and_status(_parse_max_retries, 11)
    assert code == "invalid_max_retries"
    assert message == "max_retries must be between 0 and 10."
    assert status == 400
    code, message, _ = _message_and_status(_parse_max_retries, True)
    assert message == "max_retries must be an integer."


@pytest.mark.parametrize(("value", "expected"), [(None, 1), (0, 0), (4, 4)])
def test_parse_max_retries_per_step_valid(value, expected):
    assert _parse_max_retries_per_step(value) == expected


@pytest.mark.parametrize("value", [True, "1", -1, 5])
def test_parse_max_retries_per_step_rejected(value):
    assert _code(_parse_max_retries_per_step, value) == "invalid_recovery_policy"


# ---------------------------------------------------------------------------
# subject_id
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [None, "subj-1", "a", "A.b:c@d-9", "x" * 128])
def test_parse_subject_id_valid(value):
    assert _parse_subject_id(value) == value


@pytest.mark.parametrize("value", ["", "x" * 129, "_leading", "has space", "slash/x", 5, True])
def test_parse_subject_id_rejected(value):
    assert _code(_parse_subject_id, value) == "invalid_subject_id"


# ---------------------------------------------------------------------------
# strict booleans
# ---------------------------------------------------------------------------


def test_require_strict_bool():
    assert _require_strict_bool(None, name="require_evidence") is False
    assert _require_strict_bool(True, name="require_evidence") is True
    assert _require_strict_bool(False, name="require_verification") is False


@pytest.mark.parametrize("value", ["true", 1, 0, [True]])
def test_require_strict_bool_rejects_non_bool(value):
    code, message, _ = _message_and_status(_require_strict_bool, value, name="require_evidence")
    assert code == "invalid_require_evidence"
    assert message == "require_evidence must be a boolean."


# ---------------------------------------------------------------------------
# AgentPlan wire parsing
# ---------------------------------------------------------------------------

_VALID_AGENT_ID = "agent:demo.research:v1@1"


def _valid_plan():
    return {
        "agent_id": _VALID_AGENT_ID,
        "steps": [
            {"step_id": "step_1", "objective": "do work", "tool_id": "tool.echo"},
            {"step_id": "step_2", "objective": "next", "depends_on": ["step_1"]},
        ],
    }


def test_parse_agent_plan_valid():
    plan = _parse_agent_plan(_valid_plan())
    assert plan is not None
    assert plan.agent_id == _VALID_AGENT_ID
    assert plan.steps[0].step_id == "step_1"
    assert plan.steps[0].tool_id == "tool.echo"
    assert plan.steps[1].depends_on == ("step_1",)
    assert _parse_agent_plan(None) is None


@pytest.mark.parametrize("agent_id", [
    "demo:v1@1", "agent:demo:v1", "AGENT:demo:v1@1", "agent:Demo:v1@1",
    "agent:demo:v1@0", "agent:demo:v1@-1", "agent::v1@1", "agent:demo:v1@1x",
    "", 5, None,
])
def test_parse_agent_plan_bad_agent_id(agent_id):
    payload = _valid_plan()
    payload["agent_id"] = agent_id
    assert _code(_parse_agent_plan, payload) == "invalid_plan"


def test_parse_agent_plan_unknown_field_fail_closed():
    payload = _valid_plan()
    payload["extra_authority"] = "yes"
    code, message, _ = _message_and_status(_parse_agent_plan, payload)
    assert code == "invalid_plan"
    assert message == "agent_plan contains unsupported fields."


def test_parse_agent_plan_non_object_and_bad_steps():
    assert _code(_parse_agent_plan, "nope") == "invalid_plan"
    assert _code(_parse_agent_plan, 7) == "invalid_plan"
    payload = _valid_plan()
    payload["steps"] = "step_1"
    assert _code(_parse_agent_plan, payload) == "invalid_plan"


@pytest.mark.parametrize("step", [
    {"step_id": "_bad", "objective": "x"},
    {"step_id": "ok", "objective": 5},
    {"step_id": "ok", "objective": "x", "tool_id": "_bad"},
    {"step_id": "ok", "objective": "x", "depends_on": "step_1"},
    {"step_id": "ok", "objective": "x", "depends_on": ["_bad"]},
    {"step_id": "ok", "objective": "x", "unknown": 1},
    "not-an-object",
])
def test_parse_plan_step_rejections(step):
    assert _code(_parse_plan_step, step) == "invalid_plan"


def test_parse_plan_step_minimal_defaults():
    step = _parse_plan_step({"step_id": "s1", "objective": "obj"})
    assert step.tool_id is None
    assert step.depends_on == ()


# ---------------------------------------------------------------------------
# Recovery policy
# ---------------------------------------------------------------------------


def test_parse_recovery_policy_valid_and_defaults():
    assert _parse_recovery_policy(None) is None
    policy = _parse_recovery_policy({"retryable_driver_codes": ["provider_timeout"], "max_retries_per_step": 2})
    assert policy.retryable_driver_codes == ("provider_timeout",)
    assert policy.max_retries_per_step == 2
    empty = _parse_recovery_policy({})
    assert empty.retryable_driver_codes == ()
    assert empty.max_retries_per_step == 1


@pytest.mark.parametrize("value", [
    "not-an-object",
    {"unknown_field": 1},
    {"retryable_driver_codes": "provider_timeout"},
    {"retryable_driver_codes": ["_unsafe"]},
    {"max_retries_per_step": 99},
    {"max_retries_per_step": True},
])
def test_parse_recovery_policy_rejections(value):
    assert _code(_parse_recovery_policy, value) == "invalid_recovery_policy"


def test_parse_retryable_driver_codes_empty():
    assert _parse_retryable_driver_codes([]) == ()
    assert _parse_retryable_driver_codes(("a.b-c:d",)) == ("a.b-c:d",)


# ---------------------------------------------------------------------------
# Cancel reason
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("value", "expected"), [
    (None, "user_cancelled"),
    ("accidental_run", "accidental_run"),
    ("x" * _MAX_CANCEL_REASON_LEN, "x" * _MAX_CANCEL_REASON_LEN),
])
def test_parse_cancel_reason_valid(value, expected):
    assert _parse_cancel_reason(value) == expected


@pytest.mark.parametrize("value", ["", "   ", "x" * 257, 5, True, ["reason"]])
def test_parse_cancel_reason_rejected(value):
    code, message, _ = _message_and_status(_parse_cancel_reason, value)
    assert code == "invalid_cancel_reason"
    assert message in {
        "cancel reason must be a string.",
        "cancel reason must be a bounded non-empty string.",
    }


# ---------------------------------------------------------------------------
# Approval decision wire parsing
# ---------------------------------------------------------------------------

_DECISION_REQUIRED = {"decision_id", "pause_id", "outcome", "authority_ref", "evidence_ref", "decided_at"}


def _valid_decision():
    return {
        "decision_id": "dec_1",
        "pause_id": "pause_1",
        "outcome": "approved",
        "authority_ref": "auth:control-plane:ref",
        "evidence_ref": "ev:audit:ref",
        "decided_at": "2026-09-04T12:00:00+00:00",
    }


def test_parse_approval_decision_submission_valid():
    submission = _parse_approval_decision_submission(_valid_decision())
    assert isinstance(submission, ApprovalDecisionSubmission)
    assert submission.decision_id == "dec_1"
    assert submission.outcome.value == "approved"
    assert submission.decided_at == datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


def test_approval_submission_is_untrusted_wire_only():
    # The wire model must not expose verified-authority behavior.
    assert not hasattr(ApprovalDecisionSubmission, "verify")
    assert ApprovalDecisionSubmission.__doc__ == "Untrusted wire data; never pass this type to Core resume()."


@pytest.mark.parametrize("missing", sorted(_DECISION_REQUIRED))
def test_parse_approval_decision_missing_required_field(missing):
    payload = _valid_decision()
    del payload[missing]
    code, message, _ = _message_and_status(_parse_approval_decision_submission, payload)
    assert code == "invalid_decision"
    assert message == "decision is missing required fields."


@pytest.mark.parametrize("value", ["not-an-object", None, 5])
def test_parse_approval_decision_non_object(value):
    code, message, _ = _message_and_status(_parse_approval_decision_submission, value)
    assert code == "invalid_decision"
    assert message == "decision must be an object."


@pytest.mark.parametrize("outcome", ["maybe", "", None, "APPROVED", 1])
def test_parse_approval_decision_invalid_outcome(outcome):
    payload = _valid_decision()
    payload["outcome"] = outcome
    code, message, _ = _message_and_status(_parse_approval_decision_submission, payload)
    assert code == "invalid_decision"
    assert message == "decision.outcome is invalid."


@pytest.mark.parametrize("timestamp", ["2026-09-04T12:00:00", "not-a-time", "", None, 1755000000])
def test_parse_approval_decision_bad_timestamp(timestamp):
    payload = _valid_decision()
    payload["decided_at"] = timestamp
    code, _, _ = _message_and_status(_parse_approval_decision_submission, payload)
    assert code == "invalid_trust_evidence"


def test_parse_required_timestamp_naive_rejected():
    code, message, _ = _message_and_status(
        _parse_required_timestamp, {"decided_at": "2026-09-04T12:00:00"}, "decided_at"
    )
    assert code == "invalid_trust_evidence"
    assert message == "decided_at must be timezone-aware."
    parsed = _parse_required_timestamp({"decided_at": "2026-09-04T12:00:00+09:00"}, "decided_at")
    assert parsed.utcoffset().total_seconds() == 9 * 3600


@pytest.mark.parametrize("blank", ["", "   ", None, 5])
def test_required_text_rejects_blank(blank):
    code, message, _ = _message_and_status(_required_text, {"decision_id": blank}, "decision_id")
    assert code == "invalid_trust_evidence"
    assert message == "decision_id must be explicit."


# ---------------------------------------------------------------------------
# Continuation ref
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["cont_" + "a" * 43, "cont_x", "cont_" + "z" * 121])
def test_parse_continuation_ref_valid(value):
    assert _parse_continuation_ref(value) == value


@pytest.mark.parametrize("value", [
    "tok_abc", "cont", "contx", "", "cont_" + "a" * 124, 5, None, True,
])
def test_parse_continuation_ref_rejected(value):
    code, message, status = _message_and_status(_parse_continuation_ref, value)
    assert code == "invalid_continuation"
    assert message == "continuation_ref is invalid."
    assert status == 409


# ---------------------------------------------------------------------------
# Combined orchestration options
# ---------------------------------------------------------------------------


def test_parse_orchestration_options_defaults():
    plan, policy, max_retries, subject_id, evidence, verification = _parse_orchestration_options({})
    assert plan is None
    assert policy is None
    assert max_retries == 3
    assert subject_id is None
    assert evidence is False
    assert verification is False


def test_parse_orchestration_options_full():
    payload = {
        "agent_plan": _valid_plan(),
        "recovery_policy": {"retryable_driver_codes": ["retry_me"]},
        "max_retries": 5,
        "subject_id": "subj_1",
        "require_evidence": True,
        "require_verification": False,
    }
    plan, policy, max_retries, subject_id, evidence, verification = _parse_orchestration_options(payload)
    assert plan.agent_id == _VALID_AGENT_ID
    assert policy.retryable_driver_codes == ("retry_me",)
    assert max_retries == 5
    assert subject_id == "subj_1"
    assert evidence is True
    assert verification is False


def test_agent_id_regex_bounds():
    assert _AGENT_ID_RE.fullmatch("agent:a:b@1")
    assert _AGENT_ID_RE.fullmatch("agent:a1.b-c:d1.e_f@42")
    assert not _AGENT_ID_RE.fullmatch("agent:a:b@01")
    assert _MAX_AGENT_STEP_RETRIES == 4
