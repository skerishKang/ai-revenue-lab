"""Network-free tests for the Engine trusted execution admission seam."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.execution_admission import (
    ExecutionAdmissionError,
    ExecutionAdmissionRequest,
    TrustedExecutionAdmission,
    require_trusted_admission,
)

_NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def _request(**overrides):
    data = {
        "app_id": "b62",
        "subject_id": "subject:user_1",
        "capability": "orchestration.run",
        "trace_id": "trace:admission_1",
        "request_fingerprint": "fp:abc123",
    }
    data.update(overrides)
    return ExecutionAdmissionRequest(**data)


def _admission(**overrides):
    data = {
        "decision_id": "adm:decision_1",
        "app_id": "b62",
        "subject_id": "subject:user_1",
        "capability": "orchestration.run",
        "allowed": True,
        "authority_ref": "control-plane:entitlement:rev1",
        "policy_revision": "policy:rev1",
        "issued_at": _NOW - timedelta(minutes=1),
        "expires_at": _NOW + timedelta(minutes=5),
        "request_fingerprint": "fp:abc123",
    }
    data.update(overrides)
    return TrustedExecutionAdmission(**data)


def _assert_rejected(code: str, request=None, admission=None) -> None:
    with pytest.raises(ExecutionAdmissionError) as excinfo:
        require_trusted_admission(
            request=request or _request(),
            admission=admission,
            now=_NOW,
        )
    assert excinfo.value.code == code


def test_trusted_admission_allows_matching_request() -> None:
    admission = _admission()

    result = require_trusted_admission(request=_request(), admission=admission, now=_NOW)

    assert result is admission


def test_missing_entitlement_fails_closed() -> None:
    _assert_rejected("missing_entitlement", admission=None)


def test_denied_entitlement_fails_closed() -> None:
    _assert_rejected("entitlement_denied", admission=_admission(allowed=False))


def test_expired_entitlement_fails_closed() -> None:
    _assert_rejected(
        "entitlement_expired",
        admission=_admission(
            issued_at=_NOW - timedelta(minutes=10),
            expires_at=_NOW - timedelta(seconds=1),
        ),
    )


def test_future_entitlement_fails_closed() -> None:
    _assert_rejected(
        "invalid_admission",
        admission=_admission(
            issued_at=_NOW + timedelta(seconds=1),
            expires_at=_NOW + timedelta(minutes=10),
        ),
    )


def test_app_mismatch_fails_closed() -> None:
    _assert_rejected("entitlement_app_mismatch", admission=_admission(app_id="b61"))


def test_subject_mismatch_fails_closed() -> None:
    _assert_rejected("entitlement_subject_mismatch", admission=_admission(subject_id="subject:user_2"))


def test_capability_mismatch_fails_closed() -> None:
    _assert_rejected("entitlement_capability_mismatch", admission=_admission(capability="orchestration.resume"))


def test_request_fingerprint_mismatch_fails_closed() -> None:
    _assert_rejected("entitlement_request_mismatch", admission=_admission(request_fingerprint="fp:other"))


def test_unscoped_admission_must_match_unscoped_request() -> None:
    request = _request(subject_id=None)
    admission = _admission(subject_id=None)

    result = require_trusted_admission(request=request, admission=admission, now=_NOW)

    assert result.subject_id is None


def test_subject_grant_does_not_authorize_unscoped_request() -> None:
    _assert_rejected(
        "entitlement_subject_mismatch",
        request=_request(subject_id=None),
        admission=_admission(subject_id="subject:user_1"),
    )


def test_client_shaped_entitlement_object_is_not_trusted() -> None:
    client_json = {
        "allowed": True,
        "plan": "pro",
        "credits": 999999,
        "entitlement": {"allow": True},
    }

    _assert_rejected("missing_entitlement", admission=client_json)  # type: ignore[arg-type]


def test_credit_balance_cannot_substitute_for_admission() -> None:
    _assert_rejected("missing_entitlement", admission=999999)  # type: ignore[arg-type]


def test_request_identity_binding_is_optional_but_non_widening_when_present() -> None:
    unbound = _admission(request_fingerprint=None)
    bound = _admission(request_fingerprint="fp:abc123")

    assert require_trusted_admission(request=_request(), admission=unbound, now=_NOW) is unbound
    assert require_trusted_admission(request=_request(), admission=bound, now=_NOW) is bound


def test_invalid_identifiers_are_rejected() -> None:
    with pytest.raises(ExecutionAdmissionError):
        _request(app_id="../b62")
    with pytest.raises(ExecutionAdmissionError):
        _admission(capability="orchestration run")
