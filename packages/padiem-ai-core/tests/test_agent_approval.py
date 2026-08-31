from datetime import datetime, timedelta, timezone

import pytest

from padiem_ai_core.agent_approval import (
    AgentApprovalError,
    ApprovalOutcome,
    ApprovalRequirement,
    ContinuationStatus,
    VerifiedApprovalDecision,
    approval_pause_from_tool_error,
    assert_same_invocation,
    resolve_approval_pause,
)
from padiem_ai_core.contracts import ErrorClass, RunStatus, ToolEvent
from padiem_ai_core.tool_runtime import ToolInvocation, ToolRuntimeError


NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def invocation(value: str = "alpha") -> ToolInvocation:
    return ToolInvocation(
        tool_id="tool.search",
        arguments={"query": value, "limit": 3},
    )


def approval_error(code: str) -> ToolRuntimeError:
    return ToolRuntimeError(
        code,
        "Approval is required.",
        event=ToolEvent(
            tool_id="tool.search",
            status=RunStatus.POLICY_BLOCKED,
            error_class=ErrorClass.POLICY_BLOCKED,
        ),
    )


def make_pause(*, code: str = "tool_user_confirmation_required"):
    return approval_pause_from_tool_error(
        approval_error(code),
        pause_id="pause_1",
        run_id="run_1",
        agent_runtime_id="agent.runtime.research",
        invocation=invocation(),
        step_index=2,
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=30),
    )


def decision(
    *,
    outcome: ApprovalOutcome = ApprovalOutcome.APPROVED,
    pause_id: str = "pause_1",
    decision_id: str = "decision_1",
    decided_at: datetime = NOW + timedelta(minutes=1),
) -> VerifiedApprovalDecision:
    return VerifiedApprovalDecision(
        decision_id=decision_id,
        pause_id=pause_id,
        outcome=outcome,
        authority_ref="user:owner",
        evidence_ref="approval:event:1",
        decided_at=decided_at,
    )


def test_user_confirmation_error_becomes_bounded_pause() -> None:
    pause = make_pause()
    assert pause is not None
    assert pause.requirement is ApprovalRequirement.USER_CONFIRMATION
    assert pause.tool_id == "tool.search"
    assert pause.step_index == 2
    assert len(pause.invocation_sha256) == 64


def test_external_authorization_error_maps_to_external_requirement() -> None:
    pause = make_pause(code="tool_external_authorization_required")
    assert pause is not None
    assert pause.requirement is ApprovalRequirement.EXTERNAL_AUTHORIZATION


def test_non_approval_policy_error_is_not_made_resumable() -> None:
    pause = approval_pause_from_tool_error(
        approval_error("tool_auth_scope_missing"),
        pause_id="pause_1",
        run_id="run_1",
        agent_runtime_id="agent.runtime.research",
        invocation=invocation(),
        step_index=1,
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
    )
    assert pause is None


def test_approved_decision_marks_state_resumable_without_granting_authority() -> None:
    pause = make_pause()
    assert pause is not None
    state = resolve_approval_pause(
        pause,
        decision(),
        now=NOW + timedelta(minutes=2),
    )
    assert state.status is ContinuationStatus.RESUMABLE
    assert state.decision_id == "decision_1"
    assert not hasattr(state, "granted_tools")
    assert not hasattr(state, "auth_scopes")
    assert not hasattr(state, "authorization_context")
    assert not hasattr(state, "approved_tool_ids")


def test_denied_decision_stays_terminal_for_this_pause() -> None:
    pause = make_pause()
    assert pause is not None
    state = resolve_approval_pause(
        pause,
        decision(outcome=ApprovalOutcome.DENIED),
        now=NOW + timedelta(minutes=2),
    )
    assert state.status is ContinuationStatus.DENIED


def test_expired_decision_does_not_resume() -> None:
    pause = make_pause()
    assert pause is not None
    late = decision(decided_at=NOW + timedelta(minutes=31))
    state = resolve_approval_pause(
        pause,
        late,
        now=NOW + timedelta(minutes=31),
    )
    assert state.status is ContinuationStatus.EXPIRED


def test_mismatched_pause_and_replayed_decision_fail_closed() -> None:
    pause = make_pause()
    assert pause is not None
    with pytest.raises(AgentApprovalError):
        resolve_approval_pause(
            pause,
            decision(pause_id="pause_other"),
            now=NOW + timedelta(minutes=2),
        )

    with pytest.raises(AgentApprovalError):
        resolve_approval_pause(
            pause,
            decision(),
            now=NOW + timedelta(minutes=2),
            consumed_decision_ids=frozenset({"decision_1"}),
        )


def test_resume_must_use_exact_same_tool_invocation() -> None:
    pause = make_pause()
    assert pause is not None
    assert_same_invocation(pause, invocation())

    with pytest.raises(AgentApprovalError):
        assert_same_invocation(pause, invocation("changed"))


def test_approval_pause_window_is_bounded() -> None:
    with pytest.raises(AgentApprovalError):
        approval_pause_from_tool_error(
            approval_error("tool_user_confirmation_required"),
            pause_id="pause_1",
            run_id="run_1",
            agent_runtime_id="agent.runtime.research",
            invocation=invocation(),
            step_index=1,
            created_at=NOW,
            expires_at=NOW + timedelta(hours=25),
        )


def test_naive_decision_timestamp_fails_closed() -> None:
    with pytest.raises(AgentApprovalError):
        decision(decided_at=datetime(2026, 8, 30, 12, 1))
