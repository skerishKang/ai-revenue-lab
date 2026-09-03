from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from padiem_control_plane import CanonicalSubjectRef, SubjectType
from padiem_control_plane.b14_routing_policy import (
    B14_EXTERNAL_ROUTE_GRANT_V1,
    B14_ROUTING_POLICY_VERSION_V1,
    trusted_b14_routing_policy_v1_from_entitlement,
)
from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.entitlements import EntitlementGrant, EntitlementSnapshot


NOW = datetime(2026, 9, 3, 4, 30, tzinfo=timezone.utc)
SUBJECT = CanonicalSubjectRef(
    subject_type=SubjectType.USER,
    subject_id="usr_b14_policy_001",
)


def _snapshot(*grants: EntitlementGrant, product_id: str = "padiem-chat") -> EntitlementSnapshot:
    return EntitlementSnapshot(
        snapshot_id="ent_b14_001",
        product_id=product_id,
        subject=SUBJECT,
        revision="rev_b14_001",
        issued_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(minutes=10),
        grants=tuple(grants),
    )


def _project(snapshot: EntitlementSnapshot, *, now: datetime = NOW):
    return trusted_b14_routing_policy_v1_from_entitlement(
        snapshot,
        expected_product_id="padiem-chat",
        expected_subject=SUBJECT,
        now=now,
    )


def test_v1_allows_external_routes_only_from_exact_machine_grant() -> None:
    policy = _project(
        _snapshot(EntitlementGrant(key=B14_EXTERNAL_ROUTE_GRANT_V1, allowed=True))
    )

    assert policy.policy_version == B14_ROUTING_POLICY_VERSION_V1
    assert policy.external_routes_allowed is True
    assert policy.snapshot_id == "ent_b14_001"
    assert policy.subject == SUBJECT


def test_missing_external_route_grant_denies_fail_closed() -> None:
    policy = _project(_snapshot(EntitlementGrant(key="chat.access", allowed=True)))
    assert policy.external_routes_allowed is False


def test_explicit_denied_external_route_grant_denies() -> None:
    policy = _project(
        _snapshot(EntitlementGrant(key=B14_EXTERNAL_ROUTE_GRANT_V1, allowed=False))
    )
    assert policy.external_routes_allowed is False


def test_product_mismatch_fails_closed() -> None:
    with pytest.raises(ControlPlaneContractError) as exc_info:
        _project(_snapshot(product_id="another-product"))
    assert exc_info.value.code == "b14_routing_product_mismatch"


def test_subject_mismatch_fails_closed() -> None:
    other_subject = CanonicalSubjectRef(
        subject_type=SubjectType.USER,
        subject_id="usr_other",
    )
    with pytest.raises(ControlPlaneContractError) as exc_info:
        trusted_b14_routing_policy_v1_from_entitlement(
            _snapshot(),
            expected_product_id="padiem-chat",
            expected_subject=other_subject,
            now=NOW,
        )
    assert exc_info.value.code == "b14_routing_subject_mismatch"


def test_expired_snapshot_fails_closed() -> None:
    with pytest.raises(ControlPlaneContractError) as exc_info:
        _project(_snapshot(), now=NOW + timedelta(minutes=10))
    assert exc_info.value.code == "b14_routing_snapshot_expired"


def test_future_snapshot_fails_closed() -> None:
    snapshot = EntitlementSnapshot(
        snapshot_id="ent_future",
        product_id="padiem-chat",
        subject=SUBJECT,
        revision="rev_future",
        issued_at=NOW + timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=20),
        grants=(),
    )
    with pytest.raises(ControlPlaneContractError) as exc_info:
        _project(snapshot)
    assert exc_info.value.code == "b14_routing_snapshot_not_yet_valid"


def test_naive_now_fails_closed() -> None:
    with pytest.raises(ControlPlaneContractError) as exc_info:
        _project(_snapshot(), now=datetime(2026, 9, 3, 4, 30))
    assert exc_info.value.code == "invalid_b14_routing_policy"


def test_unknown_b14_routing_grant_fails_closed_in_v1() -> None:
    with pytest.raises(ControlPlaneContractError) as exc_info:
        _project(_snapshot(EntitlementGrant(key="b14.route.domestic", allowed=True)))
    assert exc_info.value.code == "unsupported_b14_routing_entitlement"


def test_non_b14_grants_are_not_reinterpreted_as_routing_authority() -> None:
    policy = _project(
        _snapshot(
            EntitlementGrant(key="chat.access", allowed=True),
            EntitlementGrant(key="model.explicit_selection", allowed=True),
            EntitlementGrant(key="files.count", allowed=True, limit=25),
        )
    )
    assert policy.external_routes_allowed is False


def test_boolean_external_route_grant_rejects_limit_semantics() -> None:
    with pytest.raises(ControlPlaneContractError) as exc_info:
        _project(
            _snapshot(
                EntitlementGrant(
                    key=B14_EXTERNAL_ROUTE_GRANT_V1,
                    allowed=True,
                    limit=2,
                )
            )
        )
    assert exc_info.value.code == "invalid_b14_routing_entitlement"


def test_public_projection_contains_no_plan_payment_credit_or_provider_secret_truth() -> None:
    policy = _project(
        _snapshot(EntitlementGrant(key=B14_EXTERNAL_ROUTE_GRANT_V1, allowed=True))
    )
    public = policy.to_policy_dict()
    serialized = repr(public).lower()

    assert public["policy_version"] == B14_ROUTING_POLICY_VERSION_V1
    assert public["external_routes_allowed"] is True
    for forbidden in (
        "plan_name",
        "subscription",
        "payment",
        "credit_balance",
        "provider_secret",
        "credential",
        "model_tier",
        "cost_class",
    ):
        assert forbidden not in serialized
