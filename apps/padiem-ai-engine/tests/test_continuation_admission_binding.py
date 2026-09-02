"""Regression coverage for original run-admission persistence on continuations."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest

from padiem_ai_core import ApprovalPause, ApprovalRequirement

from app.continuation_binding import InMemoryIdentityBoundContinuationStore
from app.continuation_d1 import (
    _identity_from_json,
    _identity_json,
    _original_admission_from_identity_json,
)
from app.continuation_identity import ContinuationExecutionIdentity
from app.execution_admission import TrustedExecutionAdmission
from app.execution_admission_resume import OriginalAdmissionBinding


FINGERPRINT = "a" * 64


def _identity() -> ContinuationExecutionIdentity:
    return ContinuationExecutionIdentity(
        request_fingerprint="b" * 64,
        plan_fingerprint="c" * 64,
        subject_id="subject:owner",
        recovery_policy_fingerprint="d" * 64,
        max_retries=2,
        require_evidence=True,
        require_verification=False,
    )


def _pause() -> ApprovalPause:
    now = datetime.now(timezone.utc)
    return ApprovalPause(
        pause_id="pause_admission_1",
        run_id="run_admission_1",
        agent_runtime_id="agent:padiem:orchestrator_1",
        tool_id="tool_demo",
        invocation_sha256="0" * 64,
        requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=1,
        created_at=now,
        expires_at=now + timedelta(minutes=5),
        trace_id="tr_admission_pause",
    )


def _binding() -> OriginalAdmissionBinding:
    now = datetime.now(timezone.utc)
    admission = TrustedExecutionAdmission(
        decision_id="adm_run_bound_1",
        app_id="b62",
        subject_id="subject:owner",
        capability="orchestration.run",
        allowed=True,
        authority_ref="control-plane:entitlement:run",
        policy_revision="policy:run:1",
        issued_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(minutes=5),
        request_fingerprint=FINGERPRINT,
    )
    return OriginalAdmissionBinding.from_run_admission(admission)


def test_in_memory_continuation_preserves_original_run_admission() -> None:
    store = InMemoryIdentityBoundContinuationStore()
    binding = _binding()

    ref = store.issue(
        app_id="b62",
        pause=_pause(),
        execution_identity=_identity(),
        original_admission=binding,
    )
    record = store.resolve(app_id="b62", continuation_ref=ref)

    assert record.execution_identity == _identity()
    assert record.original_admission == binding


def test_legacy_continuation_without_admission_remains_readable() -> None:
    store = InMemoryIdentityBoundContinuationStore()

    ref = store.issue(
        app_id="b62",
        pause=_pause(),
        execution_identity=_identity(),
    )
    record = store.resolve(app_id="b62", continuation_ref=ref)

    assert record.original_admission is None


def test_d1_identity_envelope_round_trips_bounded_original_admission() -> None:
    identity = _identity()
    binding = _binding()

    encoded = _identity_json(identity, binding)

    assert _identity_from_json(encoded) == identity
    assert _original_admission_from_identity_json(encoded) == binding
    payload = json.loads(encoded)
    assert payload["original_admission_binding"]["decision_id"] == "adm_run_bound_1"


def test_legacy_d1_identity_json_without_admission_stays_backward_compatible() -> None:
    encoded = _identity_json(_identity())

    assert _identity_from_json(encoded) == _identity()
    assert _original_admission_from_identity_json(encoded) is None


def test_continuation_admission_envelope_excludes_raw_product_and_execution_data() -> None:
    encoded = _identity_json(_identity(), _binding())
    lowered = encoded.lower()

    for forbidden in (
        "messages",
        "credit_balance",
        "subscription",
        "payment",
        "access_token",
        "refresh_token",
        "provider_key",
        "tool_arguments",
        "model_output",
    ):
        assert forbidden not in lowered


def test_corrupt_original_admission_binding_fails_closed() -> None:
    payload = json.loads(_identity_json(_identity(), _binding()))
    payload["original_admission_binding"]["request_fingerprint"] = "not-a-sha"

    with pytest.raises(ValueError):
        _original_admission_from_identity_json(json.dumps(payload))
