"""Tests for #1241 non-widening orchestration resume admission authority."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.execution_admission import ExecutionAdmissionError, TrustedExecutionAdmission
from app.execution_admission_resume import (
    OriginalAdmissionBinding,
    require_non_widening_resume_admission,
)


NOW = datetime(2026, 9, 3, 8, 30, tzinfo=timezone(timedelta(hours=9)))
FINGERPRINT = "a" * 64
OTHER_FINGERPRINT = "b" * 64


def admission(
    *,
    capability: str,
    allowed: bool = True,
    app_id: str = "b62",
    subject_id: str | None = "subject:owner",
    request_fingerprint: str | None = FINGERPRINT,
    policy_revision: str = "policy:1",
    decision_id: str = "adm_1",
    authority_ref: str = "control-plane:entitlement:1",
) -> TrustedExecutionAdmission:
    return TrustedExecutionAdmission(
        decision_id=decision_id,
        app_id=app_id,
        subject_id=subject_id,
        capability=capability,
        allowed=allowed,
        authority_ref=authority_ref,
        policy_revision=policy_revision,
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=5),
        request_fingerprint=request_fingerprint,
    )


def original_binding() -> OriginalAdmissionBinding:
    return OriginalAdmissionBinding.from_run_admission(
        admission(capability="orchestration.run", decision_id="adm_run_1")
    )


def test_original_binding_requires_admitted_fingerprint_bound_run() -> None:
    binding = original_binding()

    assert binding.app_id == "b62"
    assert binding.subject_id == "subject:owner"
    assert binding.request_fingerprint == FINGERPRINT
    assert binding.decision_id == "adm_run_1"

    with pytest.raises(ExecutionAdmissionError) as denied:
        OriginalAdmissionBinding.from_run_admission(
            admission(capability="orchestration.run", allowed=False)
        )
    assert denied.value.code == "entitlement_denied"

    with pytest.raises(ExecutionAdmissionError) as wrong_capability:
        OriginalAdmissionBinding.from_run_admission(
            admission(capability="orchestration.resume")
        )
    assert wrong_capability.value.code == "entitlement_capability_mismatch"

    with pytest.raises(ExecutionAdmissionError) as unbound:
        OriginalAdmissionBinding.from_run_admission(
            admission(capability="orchestration.run", request_fingerprint=None)
        )
    assert unbound.value.code == "entitlement_request_mismatch"


def test_current_resume_admission_allows_new_policy_revision_without_widening_execution() -> None:
    original = original_binding()
    current = admission(
        capability="orchestration.resume",
        policy_revision="policy:expanded:2",
        decision_id="adm_resume_2",
        authority_ref="control-plane:entitlement:2",
    )

    authority = require_non_widening_resume_admission(
        original=original,
        current=current,
        expected_request_fingerprint=FINGERPRINT,
        now=NOW,
    )

    assert authority.request_fingerprint == FINGERPRINT
    assert authority.original_policy_revision == "policy:1"
    assert authority.current_policy_revision == "policy:expanded:2"
    assert authority.original_decision_id == "adm_run_1"
    assert authority.current_decision_id == "adm_resume_2"


def test_revoked_current_resume_authority_fails_closed() -> None:
    current = admission(capability="orchestration.resume", allowed=False)

    with pytest.raises(ExecutionAdmissionError) as excinfo:
        require_non_widening_resume_admission(
            original=original_binding(),
            current=current,
            expected_request_fingerprint=FINGERPRINT,
            now=NOW,
        )

    assert excinfo.value.code == "entitlement_denied"


def test_resume_expansion_cannot_change_original_execution_identity() -> None:
    current = admission(
        capability="orchestration.resume",
        request_fingerprint=OTHER_FINGERPRINT,
        policy_revision="policy:expanded:2",
    )

    with pytest.raises(ExecutionAdmissionError) as excinfo:
        require_non_widening_resume_admission(
            original=original_binding(),
            current=current,
            expected_request_fingerprint=FINGERPRINT,
            now=NOW,
        )

    assert excinfo.value.code == "entitlement_request_mismatch"


def test_unbound_current_resume_admission_is_not_authority() -> None:
    current = admission(
        capability="orchestration.resume",
        request_fingerprint=None,
    )

    with pytest.raises(ExecutionAdmissionError) as excinfo:
        require_non_widening_resume_admission(
            original=original_binding(),
            current=current,
            expected_request_fingerprint=FINGERPRINT,
            now=NOW,
        )

    assert excinfo.value.code == "entitlement_request_mismatch"


@pytest.mark.parametrize(
    ("current", "code"),
    [
        (admission(capability="orchestration.run"), "entitlement_capability_mismatch"),
        (admission(capability="orchestration.resume", app_id="b14"), "entitlement_app_mismatch"),
        (
            admission(capability="orchestration.resume", subject_id="subject:other"),
            "entitlement_subject_mismatch",
        ),
    ],
)
def test_current_resume_admission_must_match_original_app_subject_and_capability(current, code) -> None:
    with pytest.raises(ExecutionAdmissionError) as excinfo:
        require_non_widening_resume_admission(
            original=original_binding(),
            current=current,
            expected_request_fingerprint=FINGERPRINT,
            now=NOW,
        )

    assert excinfo.value.code == code


def test_continuation_material_identity_mismatch_fails_before_current_authority() -> None:
    with pytest.raises(ExecutionAdmissionError) as excinfo:
        require_non_widening_resume_admission(
            original=original_binding(),
            current=admission(capability="orchestration.resume"),
            expected_request_fingerprint=OTHER_FINGERPRINT,
            now=NOW,
        )

    assert excinfo.value.code == "continuation_admission_mismatch"
    assert excinfo.value.status_code == 409


def test_client_shaped_resume_assertion_is_never_trusted_authority() -> None:
    with pytest.raises(ExecutionAdmissionError) as excinfo:
        require_non_widening_resume_admission(
            original=original_binding(),
            current={"allow": True, "plan": "pro"},  # type: ignore[arg-type]
            expected_request_fingerprint=FINGERPRINT,
            now=NOW,
        )

    assert excinfo.value.code == "missing_entitlement"
