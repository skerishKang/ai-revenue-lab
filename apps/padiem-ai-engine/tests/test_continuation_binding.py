"""Tests for the identity-bound continuation store contract."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from padiem_ai_core import (
    AgentProfile,
    ApprovalPause,
    ApprovalRequirement,
    ExecutionContext,
    ExecutionRequest,
)

from app.continuation_binding import (
    InMemoryIdentityBoundContinuationStore,
    assert_continuation_identity,
)
from app.continuation_identity import build_continuation_execution_identity
from app.service import ServiceContractError


def _agent() -> AgentProfile:
    return AgentProfile(
        id="agent:test:continuation",
        title="Continuation",
        description="Continuation identity test agent",
        system_instruction="Be bounded.",
        task_type="general",
        optimize_for="balanced",
        max_tokens=256,
    )


def _request(content: str = "hello") -> ExecutionRequest:
    return ExecutionRequest(
        agent=_agent(),
        messages=({"role": "user", "content": content},),
        session_id="session_1",
        additional_system_context="ctx",
        trace_id="trace_1",
    )


def _pause() -> ApprovalPause:
    now = datetime.now(timezone.utc)
    return ApprovalPause(
        pause_id="pause_1",
        run_id="run_1",
        agent_runtime_id="agent:test:continuation",
        tool_id="tool_1",
        invocation_sha256="0" * 64,
        requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=1,
        created_at=now,
        expires_at=now + timedelta(minutes=5),
        trace_id="trace_1",
    )


def _identity(content: str = "hello"):
    request = _request(content)
    context = ExecutionContext(trace_id="trace_1", timeout_seconds=20)
    return build_continuation_execution_identity(
        app_id="app_1",
        request=request,
        context=context,
        subject_id="subject_1",
        plan=None,
        recovery_policy=None,
        max_retries=3,
        require_evidence=True,
        require_verification=True,
    )


def test_issue_persists_canonical_execution_identity() -> None:
    store = InMemoryIdentityBoundContinuationStore()
    identity = _identity()
    ref = store.issue(app_id="app_1", pause=_pause(), execution_identity=identity)
    record = store.resolve(app_id="app_1", continuation_ref=ref)
    assert record.execution_identity == identity
    assert record.state == "active"
    assert record.claim_token is None


def test_exact_identity_passes_before_claim() -> None:
    store = InMemoryIdentityBoundContinuationStore()
    identity = _identity()
    ref = store.issue(app_id="app_1", pause=_pause(), execution_identity=identity)
    record = store.resolve(app_id="app_1", continuation_ref=ref)
    assert_continuation_identity(record, identity)
    still_active = store.resolve(app_id="app_1", continuation_ref=ref)
    assert still_active.state == "active"
    assert still_active.claim_token is None


def test_identity_mismatch_fails_before_claim_and_leaves_active() -> None:
    store = InMemoryIdentityBoundContinuationStore()
    ref = store.issue(app_id="app_1", pause=_pause(), execution_identity=_identity())
    record = store.resolve(app_id="app_1", continuation_ref=ref)
    with pytest.raises(ServiceContractError) as excinfo:
        assert_continuation_identity(record, _identity("changed"))
    assert excinfo.value.code == "continuation_identity_mismatch"
    assert excinfo.value.status_code == 409
    after = store.resolve(app_id="app_1", continuation_ref=ref)
    assert after.state == "active"
    assert after.claim_token is None


def test_claim_commit_preserves_one_time_semantics() -> None:
    store = InMemoryIdentityBoundContinuationStore()
    ref = store.issue(app_id="app_1", pause=_pause(), execution_identity=_identity())
    claimed = store.claim(app_id="app_1", continuation_ref=ref)
    assert claimed.state == "claimed"
    assert claimed.claim_token is not None
    store.commit(
        app_id="app_1",
        continuation_ref=ref,
        claim_token=claimed.claim_token,
    )
    with pytest.raises(ServiceContractError) as excinfo:
        store.resolve(app_id="app_1", continuation_ref=ref)
    assert excinfo.value.code == "continuation_consumed"


def test_release_returns_same_identity_to_active_state() -> None:
    store = InMemoryIdentityBoundContinuationStore()
    identity = _identity()
    ref = store.issue(app_id="app_1", pause=_pause(), execution_identity=identity)
    claimed = store.claim(app_id="app_1", continuation_ref=ref)
    store.release(
        app_id="app_1",
        continuation_ref=ref,
        claim_token=claimed.claim_token or "",
    )
    record = store.resolve(app_id="app_1", continuation_ref=ref)
    assert record.state == "active"
    assert record.claim_token is None
    assert record.execution_identity == identity


def test_cancel_is_terminal_and_identity_cannot_be_reused() -> None:
    store = InMemoryIdentityBoundContinuationStore()
    ref = store.issue(app_id="app_1", pause=_pause(), execution_identity=_identity())
    cancelled = store.cancel(app_id="app_1", continuation_ref=ref)
    assert cancelled.state == "cancelled"
    with pytest.raises(ServiceContractError) as excinfo:
        store.resolve(app_id="app_1", continuation_ref=ref)
    assert excinfo.value.code == "continuation_cancelled"


def test_cross_app_reference_is_rejected() -> None:
    store = InMemoryIdentityBoundContinuationStore()
    ref = store.issue(app_id="app_1", pause=_pause(), execution_identity=_identity())
    with pytest.raises(ServiceContractError) as excinfo:
        store.resolve(app_id="app_2", continuation_ref=ref)
    assert excinfo.value.code == "invalid_continuation"
