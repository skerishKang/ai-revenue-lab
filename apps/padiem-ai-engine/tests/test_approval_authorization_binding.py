"""Regression tests for verified approval -> ToolAuthorizationContext binding (#3318)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from padiem_ai_core import (
    ApprovalOutcome,
    ApprovalPause,
    ApprovalRequirement,
    ToolAuthorizationContext,
    VerifiedApprovalDecision,
)

from app.orchestration_service import (
    bind_verified_approval_to_tool_authorization,
)
from app.service import ServiceContractError


NOW = datetime.now(timezone.utc)


def _pause(
    requirement: ApprovalRequirement = ApprovalRequirement.USER_CONFIRMATION,
) -> ApprovalPause:
    return ApprovalPause(
        pause_id="pause_auth_delta_1",
        run_id="run_auth_delta_1",
        agent_runtime_id="agent-runtime:1234567890abcdef12345678",
        tool_id="approval_smoke.confirm",
        invocation_sha256="a" * 64,
        requirement=requirement,
        step_index=1,
        created_at=NOW - timedelta(seconds=1),
        expires_at=NOW + timedelta(minutes=10),
        trace_id="tr_auth_delta_1",
        plan_id="agent:padiem:approval_smoke@1",
    )


def _decision(
    *,
    outcome: ApprovalOutcome = ApprovalOutcome.APPROVED,
    pause_id: str = "pause_auth_delta_1",
) -> VerifiedApprovalDecision:
    return VerifiedApprovalDecision(
        decision_id="dec_auth_delta_1",
        pause_id=pause_id,
        outcome=outcome,
        authority_ref="user:approval_smoke",
        evidence_ref="session:approval_smoke",
        decided_at=NOW,
    )


def _authorization() -> ToolAuthorizationContext:
    return ToolAuthorizationContext(
        app_id="b54-engine-approval-smoke",
        agent_id="agent-runtime:1234567890abcdef12345678",
        granted_auth_scopes=("approval.smoke",),
        user_confirmed_tools=("existing.confirmed",),
        externally_authorized_tools=("existing.external",),
    )


def test_approved_user_confirmation_adds_only_exact_paused_tool() -> None:
    before = _authorization()
    after = bind_verified_approval_to_tool_authorization(
        before,
        pause=_pause(),
        decision=_decision(),
    )

    assert after is not before
    assert after.app_id == before.app_id
    assert after.agent_id == before.agent_id
    assert after.granted_auth_scopes == before.granted_auth_scopes
    assert after.user_confirmed_tools == (
        "existing.confirmed",
        "approval_smoke.confirm",
    )
    assert after.externally_authorized_tools == ("existing.external",)


def test_approved_external_authorization_adds_only_exact_paused_tool() -> None:
    before = _authorization()
    after = bind_verified_approval_to_tool_authorization(
        before,
        pause=_pause(ApprovalRequirement.EXTERNAL_AUTHORIZATION),
        decision=_decision(),
    )

    assert after.user_confirmed_tools == ("existing.confirmed",)
    assert after.externally_authorized_tools == (
        "existing.external",
        "approval_smoke.confirm",
    )


def test_denied_decision_mints_no_tool_authority() -> None:
    before = _authorization()
    after = bind_verified_approval_to_tool_authorization(
        before,
        pause=_pause(),
        decision=_decision(outcome=ApprovalOutcome.DENIED),
    )
    assert after is before


def test_verified_decision_pause_mismatch_fails_closed() -> None:
    with pytest.raises(ServiceContractError) as exc:
        bind_verified_approval_to_tool_authorization(
            _authorization(),
            pause=_pause(),
            decision=_decision(pause_id="pause_other"),
        )
    assert exc.value.code == "approval_decision_mismatch"


def test_repeated_binding_is_idempotent_and_does_not_duplicate_tool() -> None:
    first = bind_verified_approval_to_tool_authorization(
        _authorization(),
        pause=_pause(),
        decision=_decision(),
    )
    second = bind_verified_approval_to_tool_authorization(
        first,
        pause=_pause(),
        decision=_decision(),
    )
    assert second.user_confirmed_tools.count("approval_smoke.confirm") == 1


def test_resume_pipeline_applies_verified_delta_before_continuation_claim() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "app" / "orchestration_service.py"
    ).read_text(encoding="utf-8")

    verify_pos = source.index("decision = await self._verify_decision")
    bind_pos = source.index(
        "bind_verified_approval_to_tool_authorization(",
        verify_pos,
    )
    claim_pos = source.index(
        'claimed_record = await self._continuation_call(\n                "claim"',
        bind_pos,
    )

    assert verify_pos < bind_pos < claim_pos
    assert "payload.get(\"user_confirmed_tools\")" not in source
    assert "payload.get(\"externally_authorized_tools\")" not in source
