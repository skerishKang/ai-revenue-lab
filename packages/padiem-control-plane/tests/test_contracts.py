from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from padiem_control_plane import (
    BillingDisposition,
    CanonicalSubjectRef,
    ControlPlaneContractError,
    CostEvidenceSource,
    IdentityLinkState,
    MonetaryCostEvidence,
    ProductIdentityLink,
    RouteEvidence,
    RouteEvidenceStatus,
    SubjectType,
    TokenUsage,
    UsageEvent,
    UsageOutcome,
    validate_usage_event_batch,
)


def _event(
    *,
    event_id: str = "use_001",
    idempotency_key: str = "padiem-chat:req_001",
    billing_semantic_id: str = "bill_001",
) -> UsageEvent:
    return UsageEvent(
        event_id=event_id,
        idempotency_key=idempotency_key,
        billing_semantic_id=billing_semantic_id,
        product_id="padiem-chat",
        subject=CanonicalSubjectRef(
            subject_type=SubjectType.USER,
            subject_id="usr_canonical_001",
        ),
        execution_id="run_001",
        outcome=UsageOutcome.SUCCEEDED,
        billing_disposition=BillingDisposition.BILLABLE,
        occurred_at=datetime(2026, 8, 30, 9, 30, tzinfo=timezone.utc),
        tokens=TokenUsage(input_tokens=51, output_tokens=11, total_tokens=62),
        route=RouteEvidence(
            status=RouteEvidenceStatus.OBSERVED,
            selected_provider="poolside",
            selected_model="poolside/laguna-s-2.1",
            selected_upstream_model="poolside/laguna-s-2.1",
            selected_route_id="poolside-direct",
            attempt_count=1,
            fallback_used=False,
        ),
        cost=MonetaryCostEvidence(
            amount=Decimal("0.001234"),
            currency="USD",
            source=CostEvidenceSource.UPSTREAM_REPORTED,
        ),
    )


def test_product_identity_link_preserves_existing_product_user_id() -> None:
    link = ProductIdentityLink(
        product_id="padiem-chat",
        product_user_id="usr_existing_b62_001",
        canonical_subject_id="usr_canonical_001",
    )

    assert link.product_user_id == "usr_existing_b62_001"
    assert link.canonical_subject_id == "usr_canonical_001"
    assert link.state is IdentityLinkState.ACTIVE
    assert link.to_public_dict() == {
        "product_id": "padiem-chat",
        "product_user_id": "usr_existing_b62_001",
        "canonical_subject_id": "usr_canonical_001",
        "state": "active",
    }


def test_usage_event_preserves_observed_poolside_route_and_precise_cost() -> None:
    event = _event()
    public = event.to_public_dict()

    assert public["tokens"] == {
        "input_tokens": 51,
        "output_tokens": 11,
        "total_tokens": 62,
    }
    assert public["route"] == {
        "status": "observed",
        "selected_provider": "poolside",
        "selected_model": "poolside/laguna-s-2.1",
        "selected_upstream_model": "poolside/laguna-s-2.1",
        "selected_route_id": "poolside-direct",
        "attempt_count": 1,
        "fallback_used": False,
    }
    assert public["cost"] == {
        "amount": "0.001234",
        "currency": "USD",
        "source": "upstream_reported",
    }


def test_unknown_usage_and_cost_remain_unknown_not_fabricated() -> None:
    event = UsageEvent(
        event_id="use_unknown",
        idempotency_key="padiem-chat:req_unknown",
        billing_semantic_id="bill_unknown",
        product_id="padiem-chat",
        subject=CanonicalSubjectRef(
            subject_type=SubjectType.ANONYMOUS,
            subject_id="anon_hash_001",
        ),
        execution_id="run_unknown",
        outcome=UsageOutcome.FAILED,
        billing_disposition=BillingDisposition.NON_BILLABLE,
        occurred_at=datetime(2026, 8, 30, 9, 31, tzinfo=timezone.utc),
    )

    assert event.tokens.is_unknown is True
    assert event.route.status is RouteEvidenceStatus.UNKNOWN
    assert event.cost is None
    public = event.to_public_dict()
    assert public["tokens"] == {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
    }
    assert public["cost"] is None


def test_usage_contract_has_no_raw_prompt_response_secret_or_arbitrary_metadata_field() -> None:
    event = _event()
    public = event.to_public_dict()

    assert "prompt" not in public
    assert "response" not in public
    assert "secret" not in public
    assert "authorization" not in public
    assert "metadata" not in public


def test_batch_rejects_duplicate_event_id_idempotency_or_billing_semantic() -> None:
    first = _event()

    with pytest.raises(ControlPlaneContractError) as exc_info:
        validate_usage_event_batch(
            (
                first,
                _event(
                    event_id="use_001",
                    idempotency_key="padiem-chat:req_002",
                    billing_semantic_id="bill_002",
                ),
            )
        )
    assert exc_info.value.code == "duplicate_usage_event"

    with pytest.raises(ControlPlaneContractError):
        validate_usage_event_batch(
            (
                first,
                _event(
                    event_id="use_002",
                    idempotency_key="padiem-chat:req_001",
                    billing_semantic_id="bill_002",
                ),
            )
        )

    with pytest.raises(ControlPlaneContractError):
        validate_usage_event_batch(
            (
                first,
                _event(
                    event_id="use_002",
                    idempotency_key="padiem-chat:req_002",
                    billing_semantic_id="bill_001",
                ),
            )
        )


def test_invalid_usage_values_cost_and_unknown_route_fail_closed() -> None:
    with pytest.raises(ControlPlaneContractError) as exc_info:
        TokenUsage(input_tokens=-1)
    assert exc_info.value.code == "invalid_usage_value"

    with pytest.raises(ControlPlaneContractError) as exc_info:
        MonetaryCostEvidence(
            amount=Decimal("-0.1"),
            currency="USD",
            source=CostEvidenceSource.MEASURED,
        )
    assert exc_info.value.code == "invalid_cost_evidence"

    with pytest.raises(ControlPlaneContractError):
        MonetaryCostEvidence(
            amount=Decimal("1.0"),
            currency="usd",
            source=CostEvidenceSource.MEASURED,
        )

    with pytest.raises(ControlPlaneContractError) as exc_info:
        RouteEvidence(
            status=RouteEvidenceStatus.UNKNOWN,
            selected_provider="poolside",
        )
    assert exc_info.value.code == "invalid_route_evidence"


def test_usage_event_requires_timezone_aware_server_timestamp() -> None:
    with pytest.raises(ControlPlaneContractError) as exc_info:
        UsageEvent(
            event_id="use_naive",
            idempotency_key="padiem-chat:req_naive",
            billing_semantic_id="bill_naive",
            product_id="padiem-chat",
            subject=CanonicalSubjectRef(
                subject_type=SubjectType.USER,
                subject_id="usr_canonical_001",
            ),
            execution_id="run_naive",
            outcome=UsageOutcome.SUCCEEDED,
            billing_disposition=BillingDisposition.BILLABLE,
            occurred_at=datetime(2026, 8, 30, 9, 30),
        )
    assert exc_info.value.code == "invalid_timestamp"
