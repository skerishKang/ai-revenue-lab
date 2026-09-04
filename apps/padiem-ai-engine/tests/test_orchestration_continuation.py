"""Direct behavioral tests for the extracted continuation contract/store module.

These lock the #1792 R2B-1 extraction: the record shape, CAS lifecycle
transitions, cancel semantics, expiry checks, app_id scoping, and the exact
error taxonomy must match the pre-extraction behavior of
``app.orchestration_service``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from padiem_ai_core import ApprovalPause, ApprovalRequirement

from app.orchestration_continuation import (
    ContinuationRecord,
    ContinuationStore,
    InMemoryContinuationStore,
)
from app.service import ServiceContractError

_NOW = datetime.now(timezone.utc)


def _pause(*, expires_at: datetime | None = None) -> ApprovalPause:
    created = _NOW - timedelta(hours=2)
    return ApprovalPause(
        pause_id="pause_1",
        run_id="run_1",
        agent_runtime_id="agent_runtime_1",
        tool_id="tool.echo",
        invocation_sha256="a" * 64,
        requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=1,
        created_at=created,
        expires_at=expires_at if expires_at is not None else _NOW + timedelta(hours=1),
        trace_id="trace_1",
    )


def _issue(store: InMemoryContinuationStore, *, pause: ApprovalPause | None = None) -> str:
    return store.issue(
        app_id="app_a",
        pause=pause or _pause(),
        plan_id="plan_1",
        idempotency_key="idem_1",
        request_fingerprint="fp_1",
    )


def _code(fn, *args, **kwargs) -> str:
    with pytest.raises(ServiceContractError) as excinfo:
        fn(*args, **kwargs)
    return excinfo.value.code


def test_compat_reexports_are_the_same_objects():
    import app.orchestration_service as orchestration_service

    assert orchestration_service.ContinuationRecord is ContinuationRecord
    assert orchestration_service.ContinuationStore is ContinuationStore
    assert orchestration_service.InMemoryContinuationStore is InMemoryContinuationStore


def test_issue_and_resolve_roundtrip():
    store = InMemoryContinuationStore()
    pause = _pause()
    ref = _issue(store, pause=pause)

    assert ref.startswith("cont_")
    record = store.resolve(app_id="app_a", continuation_ref=ref)
    assert isinstance(record, ContinuationRecord)
    assert record.app_id == "app_a"
    assert record.pause is pause
    assert record.continuation_ref == ref
    assert record.plan_id == "plan_1"
    assert record.idempotency_key == "idem_1"
    assert record.request_fingerprint == "fp_1"
    assert record.state == "active"
    assert record.claim_token is None
    assert record.cancel_reason is None
    assert record.cancel_event_fingerprint is None


def test_resolve_rejects_unknown_ref_wrong_app_and_bad_format():
    store = InMemoryContinuationStore()
    ref = _issue(store)

    assert _code(store.resolve, app_id="app_a", continuation_ref="cont_missing") == "invalid_continuation"
    assert _code(store.resolve, app_id="app_b", continuation_ref=ref) == "invalid_continuation"
    assert _code(store.resolve, app_id="app_a", continuation_ref="not_a_ref") == "invalid_continuation"
    assert _code(store.resolve, app_id="app_a", continuation_ref=None) == "invalid_continuation"


def test_resolve_error_carries_conflict_status():
    store = InMemoryContinuationStore()
    with pytest.raises(ServiceContractError) as excinfo:
        store.resolve(app_id="app_a", continuation_ref="cont_missing")
    assert excinfo.value.status_code == 409
    assert excinfo.value.safe_message == "Continuation reference is invalid."


def test_claim_commit_lifecycle():
    store = InMemoryContinuationStore()
    ref = _issue(store)

    claimed = store.claim(app_id="app_a", continuation_ref=ref)
    assert claimed.state == "claimed"
    assert claimed.claim_token is not None and claimed.claim_token.startswith("claim_")
    assert _code(store.claim, app_id="app_a", continuation_ref=ref) == "continuation_claimed"

    assert store.commit(app_id="app_a", continuation_ref=ref, claim_token=claimed.claim_token) is None
    assert _code(store.resolve, app_id="app_a", continuation_ref=ref) == "continuation_consumed"
    assert _code(
        store.commit, app_id="app_a", continuation_ref=ref, claim_token=claimed.claim_token
    ) == "continuation_consumed"


def test_commit_and_release_reject_foreign_claim_token():
    store = InMemoryContinuationStore()
    ref = _issue(store)
    store.claim(app_id="app_a", continuation_ref=ref)

    assert _code(store.commit, app_id="app_a", continuation_ref=ref, claim_token="claim_wrong") == "continuation_claim_failed"
    assert _code(store.release, app_id="app_a", continuation_ref=ref, claim_token="claim_wrong") == "continuation_claim_failed"


def test_release_returns_record_to_active():
    store = InMemoryContinuationStore()
    ref = _issue(store)
    claimed = store.claim(app_id="app_a", continuation_ref=ref)

    assert store.release(app_id="app_a", continuation_ref=ref, claim_token=claimed.claim_token) is None
    record = store.resolve(app_id="app_a", continuation_ref=ref)
    assert record.state == "active"
    assert record.claim_token is None


def test_release_of_expired_pause_marks_expired():
    store = InMemoryContinuationStore()
    ref = _issue(store, pause=_pause(expires_at=_NOW + timedelta(seconds=5)))
    claimed = store.claim(app_id="app_a", continuation_ref=ref)
    store._records[ref] = store._copy(claimed, pause=_pause(expires_at=_NOW - timedelta(seconds=1)))

    store.release(app_id="app_a", continuation_ref=ref, claim_token=claimed.claim_token)
    assert _code(store.resolve, app_id="app_a", continuation_ref=ref) == "continuation_expired"


def test_expiry_check_on_access():
    store = InMemoryContinuationStore()
    ref = _issue(store, pause=_pause(expires_at=_NOW - timedelta(seconds=1)))

    assert _code(store.resolve, app_id="app_a", continuation_ref=ref) == "continuation_expired"
    assert store._records[ref].state == "expired"
    assert store._records[ref].claim_token is None
    assert _code(store.resolve, app_id="app_a", continuation_ref=ref) == "continuation_expired"


def test_cancel_lifecycle():
    store = InMemoryContinuationStore()
    ref = _issue(store)

    cancelling = store.claim_cancel(app_id="app_a", continuation_ref=ref, reason="user_abort")
    assert cancelling.state == "cancelling"
    assert cancelling.claim_token.startswith("cancel_")
    assert cancelling.cancel_reason == "user_abort"
    assert cancelling.cancel_event_fingerprint is None

    assert _code(store.claim, app_id="app_a", continuation_ref=ref) == "continuation_cancel_in_progress"
    assert _code(store.claim_cancel, app_id="app_a", continuation_ref=ref, reason="again") == "continuation_cancel_in_progress"

    cancelled = store.commit_cancel(app_id="app_a", continuation_ref=ref, claim_token=cancelling.claim_token)
    assert cancelled.state == "cancelled"
    assert cancelled.claim_token is None
    assert cancelled.cancel_event_fingerprint.startswith("evt_")
    assert _code(store.resolve, app_id="app_a", continuation_ref=ref) == "continuation_cancelled"


def test_release_cancel_restores_active_and_clears_cancel_fields():
    store = InMemoryContinuationStore()
    ref = _issue(store)
    cancelling = store.claim_cancel(app_id="app_a", continuation_ref=ref, reason="user_abort")

    released = store.release_cancel(app_id="app_a", continuation_ref=ref, claim_token=cancelling.claim_token)
    assert released.state == "active"
    assert released.claim_token is None
    assert released.cancel_reason is None
    assert released.cancel_event_fingerprint is None
    record = store.resolve(app_id="app_a", continuation_ref=ref)
    assert record.state == "active"


def test_release_cancel_of_expired_pause_marks_expired():
    store = InMemoryContinuationStore()
    ref = _issue(store, pause=_pause(expires_at=_NOW + timedelta(seconds=5)))
    cancelling = store.claim_cancel(app_id="app_a", continuation_ref=ref, reason="user_abort")
    store._records[ref] = store._copy(cancelling, pause=_pause(expires_at=_NOW - timedelta(seconds=1)))

    released = store.release_cancel(app_id="app_a", continuation_ref=ref, claim_token=cancelling.claim_token)
    assert released.state == "expired"


def test_cancel_claim_failures():
    store = InMemoryContinuationStore()
    ref = _issue(store)
    cancelling = store.claim_cancel(app_id="app_a", continuation_ref=ref, reason="user_abort")

    assert _code(
        store.commit_cancel, app_id="app_a", continuation_ref=ref, claim_token="cancel_wrong"
    ) == "continuation_cancel_claim_failed"
    assert _code(
        store.release_cancel, app_id="app_a", continuation_ref=ref, claim_token="cancel_wrong"
    ) == "continuation_cancel_claim_failed"
    assert _code(store.commit_cancel, app_id="app_b", continuation_ref=ref, claim_token=cancelling.claim_token) == "invalid_continuation"


def test_direct_cancel_marks_cancelled():
    store = InMemoryContinuationStore()
    ref = _issue(store)

    cancelled = store.cancel(app_id="app_a", continuation_ref=ref)
    assert cancelled.state == "cancelled"
    assert cancelled.claim_token is None
    assert _code(store.cancel, app_id="app_a", continuation_ref=ref) == "continuation_cancelled"


def test_claim_after_consumed_is_rejected():
    store = InMemoryContinuationStore()
    ref = _issue(store)
    claimed = store.claim(app_id="app_a", continuation_ref=ref)
    store.commit(app_id="app_a", continuation_ref=ref, claim_token=claimed.claim_token)

    assert _code(store.claim, app_id="app_a", continuation_ref=ref) == "continuation_consumed"
    assert _code(store.claim_cancel, app_id="app_a", continuation_ref=ref, reason="late") == "continuation_consumed"


def test_issuance_is_independent_per_store_instance():
    first = InMemoryContinuationStore()
    second = InMemoryContinuationStore()
    ref = _issue(first)
    assert _code(second.resolve, app_id="app_a", continuation_ref=ref) == "invalid_continuation"
