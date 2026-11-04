"""261105: 교차 시계 비교에 서버 시계 허용 오차를 둔다(#6875 시계 점검 후속).

#6869가 예약 경로(reserved_at)만 고친 뒤에도 같은 "from the future" 0허용
비교가 스냅샷·실행 승인·승인 결정 경로에 남아 있었다. Control Plane 시계가
몇 초 빨라도 요청 전체가 거절될 수 있다. 서버↔서버 허용(5초) 안의 앞섬은
받아들이고 그 밖은 거절하며, 만료(expires_at)와 창 검사는 그대로임을
확인한다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.approval_verifier import AuthenticatedFirstPartyApprovalDecisionVerifier
from app.execution_admission import (
    ExecutionAdmissionError,
    ExecutionAdmissionRequest,
    TrustedExecutionAdmission,
    require_trusted_admission,
)
from app.service import ServiceContractError
from app.tenant_auth import TenantIdentity, parse_entitlement_snapshot
from padiem_ai_core.agent_approval import (
    ApprovalOutcome,
    ApprovalPause,
    ApprovalRequirement,
)
from padiem_ai_core.clock_skew import SERVER_CLOCK_SKEW_TOLERANCE

NOW = datetime(2026, 11, 5, 5, 30, tzinfo=timezone.utc)


def _expected() -> TenantIdentity:
    return TenantIdentity(
        product_id="b62",
        subject_type="user",
        subject_id="sub_" + "a" * 32,
        execution_app_id="padiem_chat_b62",
    )


def _snapshot(issued_at: datetime) -> dict:
    return {
        "snapshot_id": "snap_" + "a" * 32,
        "product_id": "b62",
        "revision": "rev_" + "a" * 8,
        "subject": {"subject_type": "user", "subject_id": "sub_" + "a" * 32},
        "issued_at": issued_at.isoformat(),
        "expires_at": (issued_at + timedelta(hours=1)).isoformat(),
        "grants": [{"key": "orchestration.run", "allowed": True, "limit": None}],
    }


def _request() -> ExecutionAdmissionRequest:
    return ExecutionAdmissionRequest(
        app_id="padiem_chat_b62",
        subject_id="sub_" + "a" * 32,
        capability="orchestration.run",
    )


def _admission(issued_at: datetime) -> TrustedExecutionAdmission:
    return TrustedExecutionAdmission(
        decision_id="dec_" + "a" * 8,
        app_id="padiem_chat_b62",
        subject_id="sub_" + "a" * 32,
        capability="orchestration.run",
        allowed=True,
        authority_ref="authority_1",
        policy_revision="rev_" + "a" * 8,
        issued_at=issued_at,
        expires_at=issued_at + timedelta(hours=1),
    )


def _pause() -> ApprovalPause:
    now = datetime.now(timezone.utc)
    return ApprovalPause(
        pause_id="pause_" + "a" * 8,
        run_id="run_" + "a" * 8,
        agent_runtime_id="runtime_" + "a" * 8,
        tool_id="tool_" + "a" * 8,
        invocation_sha256="a" * 64,
        requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=1,
        created_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(minutes=10),
    )


def _submission(decided_at: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        pause_id="pause_" + "a" * 8,
        decided_at=decided_at,
        outcome="approved",
        decision_id="decision_" + "a" * 8,
        authority_ref="authority_1",
        evidence_ref="evidence_1",
    )


def test_snapshot_issued_within_server_skew_is_tolerated():
    view = parse_entitlement_snapshot(
        _snapshot(NOW + timedelta(seconds=3)), expected=_expected(), now=NOW)
    assert view.snapshot_id == "snap_" + "a" * 32


def test_snapshot_issued_beyond_server_skew_is_refused():
    with pytest.raises(ExecutionAdmissionError) as raised:
        parse_entitlement_snapshot(
            _snapshot(NOW + SERVER_CLOCK_SKEW_TOLERANCE + timedelta(seconds=1)),
            expected=_expected(),
            now=NOW,
        )
    assert raised.value.code == "invalid_admission"


def test_admission_issued_within_server_skew_is_tolerated():
    admitted = require_trusted_admission(
        request=_request(),
        admission=_admission(NOW + timedelta(seconds=3)),
        now=NOW,
    )
    assert admitted.allowed is True


def test_admission_issued_beyond_server_skew_is_refused():
    with pytest.raises(ExecutionAdmissionError) as raised:
        require_trusted_admission(
            request=_request(),
            admission=_admission(NOW + SERVER_CLOCK_SKEW_TOLERANCE + timedelta(seconds=1)),
            now=NOW,
        )
    assert raised.value.code == "invalid_admission"


def test_approval_decision_within_server_skew_is_tolerated():
    decision = AuthenticatedFirstPartyApprovalDecisionVerifier().verify(
        _submission(datetime.now(timezone.utc) + timedelta(seconds=3)),
        pause=_pause(),
        app_id="padiem_chat_b62",
    )
    assert decision.outcome == ApprovalOutcome.APPROVED


def test_approval_decision_beyond_server_skew_is_refused():
    with pytest.raises(ServiceContractError) as raised:
        AuthenticatedFirstPartyApprovalDecisionVerifier().verify(
            _submission(
                datetime.now(timezone.utc) + SERVER_CLOCK_SKEW_TOLERANCE + timedelta(seconds=1)),
            pause=_pause(),
            app_id="padiem_chat_b62",
        )
    assert "from the future" in str(raised.value)
