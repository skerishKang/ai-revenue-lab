from __future__ import annotations

import json

import pytest

from app.error_contract import (
    RetryProtocol,
    current_engine_error_taxonomy,
    engine_error_contract,
)


def test_error_taxonomy_has_unique_machine_codes() -> None:
    taxonomy = current_engine_error_taxonomy()
    codes = [item.code for item in taxonomy]

    assert taxonomy
    assert len(codes) == len(set(codes))


def test_public_error_taxonomy_contains_no_sensitive_exception_text() -> None:
    serialized = json.dumps(
        [item.to_public_dict() for item in current_engine_error_taxonomy()],
        sort_keys=True,
    ).lower()

    for forbidden in (
        "api_key",
        "authorization",
        "credential",
        "private_provider_secret",
        "trace=",
        "stacktrace",
        "raw exception",
    ):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    ("code", "status_code", "retryable", "retry_protocol"),
    [
        ("invalid_request", 400, False, RetryProtocol.NONE),
        ("invalid_json", 400, False, RetryProtocol.NONE),
        ("unsupported_media_type", 415, False, RetryProtocol.NONE),
        ("request_too_large", 413, False, RetryProtocol.NONE),
        ("execution_context_unavailable", 422, False, RetryProtocol.NONE),
        ("idempotency_conflict", 409, False, RetryProtocol.NONE),
        ("stream_idempotency_unavailable", 422, False, RetryProtocol.NONE),
        ("engine_internal_error", 500, False, RetryProtocol.NONE),
    ],
)
def test_non_retryable_errors_do_not_authorize_blind_rerun(
    code: str,
    status_code: int,
    retryable: bool,
    retry_protocol: RetryProtocol,
) -> None:
    contract = engine_error_contract(code)

    assert contract.status_code == status_code
    assert contract.retryable is retryable
    assert contract.retry_protocol is retry_protocol


@pytest.mark.parametrize(
    "code",
    [
        "invalid_continuation",
        "continuation_claimed",
        "continuation_consumed",
        "continuation_expired",
    ],
)
def test_continuation_family_uses_stable_409_semantics(code: str) -> None:
    contract = engine_error_contract(code)

    assert contract.status_code == 409
    assert contract.retryable is False
    assert contract.retry_protocol in {
        RetryProtocol.NONE,
        RetryProtocol.SAME_CONTINUATION_REF,
    }
    assert any(surface.startswith("orchestration_") for surface in contract.surfaces)


def test_transient_unavailable_codes_define_explicit_recovery_protocols() -> None:
    b14 = engine_error_contract("b14_service_unavailable")
    continuation = engine_error_contract("continuation_store_unavailable")
    approval = engine_error_contract("approval_verification_unavailable")

    assert b14.status_code == 503
    assert b14.retryable is True
    assert b14.retry_protocol is RetryProtocol.NEW_REQUEST_ALLOWED

    assert continuation.status_code == 503
    assert continuation.retryable is False
    assert continuation.retry_protocol is RetryProtocol.SAME_CONTINUATION_REF

    assert approval.status_code == 503
    assert approval.retryable is False
    assert approval.retry_protocol is RetryProtocol.SAME_CONTINUATION_REF


def test_same_machine_code_has_one_status_and_retry_contract() -> None:
    seen: dict[str, tuple[int, bool, RetryProtocol]] = {}
    for item in current_engine_error_taxonomy():
        observed = (item.status_code, item.retryable, item.retry_protocol)
        if item.code in seen:
            assert seen[item.code] == observed
        seen[item.code] = observed


def test_unknown_error_code_fails_closed() -> None:
    with pytest.raises(ValueError):
        engine_error_contract("unknown_private_error")


def test_retryable_never_means_repeat_side_effecting_operation_without_protocol() -> None:
    for item in current_engine_error_taxonomy():
        if item.retryable:
            assert item.retry_protocol is not RetryProtocol.NONE
        if item.code in {
            "idempotency_conflict",
            "continuation_claimed",
            "continuation_consumed",
            "continuation_expired",
            "approval_verification_unavailable",
            "continuation_store_unavailable",
        }:
            assert item.retryable is False
