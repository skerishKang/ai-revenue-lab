"""Product-neutral wire contract parsing for the Engine orchestration service.

Extracted verbatim from ``app.orchestration_service`` as part of the #1792 R2B-2
structural decomposition: route constants, identifier validation bounds,
strict request option parsers, AgentPlan/recovery-policy wire parsing,
approval-decision wire parsing, and the untrusted ApprovalDecisionSubmission
wire model. Behavior, defaults, regex bounds, and error taxonomy are unchanged.
The trusted ApprovalDecisionVerifier adapter contract intentionally remains in
the orchestration service.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any

from collections.abc import Mapping

from padiem_ai_core.agent_approval import ApprovalOutcome
from padiem_ai_core.agent_planner import AgentPlan, AgentPlanStep
from padiem_ai_core.agent_recovery import AgentRecoveryPolicy

from app.service import ServiceContractError


ORCHESTRATE_PATH = "/internal/v1/orchestrate"
ORCHESTRATE_RESUME_PATH = "/internal/v1/orchestrate/resume"
ORCHESTRATE_CANCEL_PATH = "/internal/v1/orchestrate/cancel"

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_AGENT_ID_RE = re.compile(
    r"^agent:[a-z0-9][a-z0-9._-]{0,63}:[a-z0-9][a-z0-9._-]{0,63}@[1-9][0-9]*$"
)

_MAX_ORCHESTRATION_RETRIES = 10
_MAX_AGENT_STEP_RETRIES = 4
_MAX_CANCEL_REASON_LEN = 256

_EXEC_FIELDS = frozenset({
    "app_id", "agent", "messages", "session_id", "additional_system_context",
    "trace_id", "execution_context",
})
_ORCHESTRATION_OPTIONS = frozenset({
    "agent_plan", "recovery_policy", "max_retries", "subject_id",
    "require_evidence", "require_verification",
})
_ORCHESTRATION_RESUME_OPTIONS = frozenset({
    "agent_plan", "recovery_policy", "max_retries", "subject_id",
})
_ORCHESTRATE_ALLOWED = _EXEC_FIELDS | _ORCHESTRATION_OPTIONS | {"tool_arguments"}
_RESUME_ALLOWED = (
    _EXEC_FIELDS | {"continuation_ref", "decision", "tool_arguments"}
) | _ORCHESTRATION_RESUME_OPTIONS
_CANCEL_ALLOWED = frozenset({"app_id", "continuation_ref", "reason"})

_AGENT_PLAN_ALLOWED = frozenset({"agent_id", "steps"})
_PLAN_STEP_ALLOWED = frozenset({"step_id", "objective", "tool_id", "depends_on"})
_RECOVERY_ALLOWED = frozenset({"retryable_driver_codes", "max_retries_per_step"})


@dataclass(frozen=True, slots=True)
class ApprovalDecisionSubmission:
    """Untrusted wire data; never pass this type to Core resume()."""

    decision_id: str
    pause_id: str
    outcome: ApprovalOutcome
    authority_ref: str
    evidence_ref: str
    decided_at: datetime


def _parse_max_retries(value: Any) -> int:
    if value is None:
        return 3
    if isinstance(value, bool) or not isinstance(value, int):
        raise ServiceContractError("invalid_max_retries", "max_retries must be an integer.")
    if not 0 <= value <= _MAX_ORCHESTRATION_RETRIES:
        raise ServiceContractError(
            "invalid_max_retries",
            f"max_retries must be between 0 and {_MAX_ORCHESTRATION_RETRIES}.",
        )
    return value


def _parse_max_retries_per_step(value: Any) -> int:
    if value is None:
        return 1
    if isinstance(value, bool) or not isinstance(value, int):
        raise ServiceContractError("invalid_recovery_policy", "max_retries_per_step must be an integer.")
    if not 0 <= value <= _MAX_AGENT_STEP_RETRIES:
        raise ServiceContractError(
            "invalid_recovery_policy",
            f"max_retries_per_step must be between 0 and {_MAX_AGENT_STEP_RETRIES}.",
        )
    return value


def _parse_subject_id(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise ServiceContractError("invalid_subject_id", "subject_id must be a bounded safe identifier.")
    return value


def _require_strict_bool(value: Any, *, name: str) -> bool:
    if value is None:
        return False
    if not isinstance(value, bool):
        raise ServiceContractError(f"invalid_{name}", f"{name} must be a boolean.")
    return value


def _parse_retryable_driver_codes(value: Any) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise ServiceContractError("invalid_recovery_policy", "retryable_driver_codes must be an array of strings.")
    codes: list[str] = []
    for code in tuple(value):
        if not isinstance(code, str) or not _IDENTIFIER_RE.fullmatch(code):
            raise ServiceContractError(
                "invalid_recovery_policy",
                "retryable_driver_codes must contain bounded safe identifiers.",
            )
        codes.append(code)
    return tuple(codes)


def _parse_plan_step(value: Any) -> AgentPlanStep:
    if not isinstance(value, Mapping):
        raise ServiceContractError("invalid_plan", "each plan step must be an object.")
    data = dict(value)
    unknown = set(data) - _PLAN_STEP_ALLOWED
    if unknown:
        raise ServiceContractError("invalid_plan", "plan step contains unsupported fields.")
    step_id = data.get("step_id", "")
    if not isinstance(step_id, str) or not _IDENTIFIER_RE.fullmatch(step_id):
        raise ServiceContractError("invalid_plan", "plan step.step_id must be a bounded safe identifier.")
    objective = data.get("objective", "")
    if not isinstance(objective, str):
        raise ServiceContractError("invalid_plan", "plan step.objective must be a string.")
    raw_tool_id = data.get("tool_id", None)
    tool_id: str | None = None
    if raw_tool_id is not None:
        if not isinstance(raw_tool_id, str) or not _IDENTIFIER_RE.fullmatch(raw_tool_id):
            raise ServiceContractError("invalid_plan", "plan step.tool_id must be a bounded safe identifier or null.")
        tool_id = raw_tool_id
    raw_depends_on = data.get("depends_on", ())
    if isinstance(raw_depends_on, (str, bytes)) or not isinstance(raw_depends_on, (list, tuple)):
        raise ServiceContractError("invalid_plan", "plan step.depends_on must be an array of strings.")
    depends_on: tuple[str, ...] = ()
    for dep in raw_depends_on:
        if not isinstance(dep, str) or not _IDENTIFIER_RE.fullmatch(dep):
            raise ServiceContractError("invalid_plan", "plan step.depends_on must contain bounded safe identifiers.")
        depends_on += (dep,)
    return AgentPlanStep(
        step_id=step_id,
        objective=objective,
        tool_id=tool_id,
        depends_on=depends_on,
    )


def _parse_agent_plan(value: Any) -> AgentPlan | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ServiceContractError("invalid_plan", "agent_plan must be an object.")
    data = dict(value)
    unknown = set(data) - _AGENT_PLAN_ALLOWED
    if unknown:
        raise ServiceContractError("invalid_plan", "agent_plan contains unsupported fields.")
    agent_id = data.get("agent_id")
    if not isinstance(agent_id, str) or not _AGENT_ID_RE.fullmatch(agent_id):
        raise ServiceContractError("invalid_plan", "agent_plan.agent_id must be a canonical versioned Agent id.")
    raw_steps = data.get("steps", ())
    if isinstance(raw_steps, (str, bytes)) or not isinstance(raw_steps, (list, tuple)):
        raise ServiceContractError("invalid_plan", "agent_plan.steps must be an array.")
    steps: list[AgentPlanStep] = [_parse_plan_step(step_item) for step_item in raw_steps]
    return AgentPlan(agent_id=agent_id, steps=tuple(steps))


def _parse_recovery_policy(value: Any) -> AgentRecoveryPolicy | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ServiceContractError("invalid_recovery_policy", "recovery_policy must be an object.")
    data = dict(value)
    unknown = set(data) - _RECOVERY_ALLOWED
    if unknown:
        raise ServiceContractError("invalid_recovery_policy", "recovery_policy contains unsupported fields.")
    return AgentRecoveryPolicy(
        retryable_driver_codes=_parse_retryable_driver_codes(data.get("retryable_driver_codes", ())),
        max_retries_per_step=_parse_max_retries_per_step(data.get("max_retries_per_step", 1)),
    )


def _parse_cancel_reason(value: Any) -> str:
    reason = value if value is not None else "user_cancelled"
    if not isinstance(reason, str):
        raise ServiceContractError("invalid_cancel_reason", "cancel reason must be a string.")
    if not reason.strip():
        raise ServiceContractError("invalid_cancel_reason", "cancel reason must be a bounded non-empty string.")
    if not (1 <= len(reason) <= _MAX_CANCEL_REASON_LEN):
        raise ServiceContractError("invalid_cancel_reason", "cancel reason must be a bounded non-empty string.")
    return reason


def _parse_orchestration_options(payload: Mapping[str, Any]) -> tuple[
    AgentPlan | None, AgentRecoveryPolicy | None, int, str | None, bool, bool
]:
    plan = _parse_agent_plan(payload.get("agent_plan"))
    rec_policy = _parse_recovery_policy(payload.get("recovery_policy"))
    max_retries = _parse_max_retries(payload.get("max_retries", 3))
    subject_id = _parse_subject_id(payload.get("subject_id"))
    require_evidence = _require_strict_bool(payload.get("require_evidence"), name="require_evidence")
    require_verification = _require_strict_bool(payload.get("require_verification"), name="require_verification")
    return plan, rec_policy, max_retries, subject_id, require_evidence, require_verification


def _parse_required_timestamp(data: Mapping[str, Any], name: str) -> datetime:
    value = data.get(name)
    if not isinstance(value, str) or not value:
        raise ServiceContractError("invalid_trust_evidence", f"{name} must be explicit.")
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise ServiceContractError("invalid_trust_evidence", f"{name} must be a valid timestamp.") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ServiceContractError("invalid_trust_evidence", f"{name} must be timezone-aware.")
    return parsed


def _required_text(data: Mapping[str, Any], name: str) -> str:
    value = data.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ServiceContractError("invalid_trust_evidence", f"{name} must be explicit.")
    return value


def _parse_approval_decision_submission(value: Any) -> ApprovalDecisionSubmission:
    if not isinstance(value, Mapping):
        raise ServiceContractError("invalid_decision", "decision must be an object.")
    data = dict(value)
    required = {"decision_id", "pause_id", "outcome", "authority_ref", "evidence_ref", "decided_at"}
    if required - set(data):
        raise ServiceContractError("invalid_decision", "decision is missing required fields.")
    try:
        outcome = ApprovalOutcome(data["outcome"])
    except (TypeError, ValueError):
        raise ServiceContractError("invalid_decision", "decision.outcome is invalid.") from None
    return ApprovalDecisionSubmission(
        decision_id=_required_text(data, "decision_id"),
        pause_id=_required_text(data, "pause_id"),
        outcome=outcome,
        authority_ref=_required_text(data, "authority_ref"),
        evidence_ref=_required_text(data, "evidence_ref"),
        decided_at=_parse_required_timestamp(data, "decided_at"),
    )


def _parse_continuation_ref(value: Any) -> str:
    if not isinstance(value, str) or not value.startswith("cont_") or len(value) > 128:
        raise ServiceContractError("invalid_continuation", "continuation_ref is invalid.", status_code=409)
    return value


