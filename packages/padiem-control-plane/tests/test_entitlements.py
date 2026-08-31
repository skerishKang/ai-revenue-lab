from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from padiem_control_plane import CanonicalSubjectRef, SubjectType
from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.entitlements import EntitlementGrant, EntitlementSnapshot


def _snapshot(*grants: EntitlementGrant) -> EntitlementSnapshot:
    issued = datetime(2026, 8, 30, 11, 30, tzinfo=timezone.utc)
    return EntitlementSnapshot(
        snapshot_id="ent_snap_001",
        product_id="padiem-chat",
        subject=CanonicalSubjectRef(
            subject_type=SubjectType.USER,
            subject_id="usr_canonical_001",
        ),
        revision="rev_001",
        issued_at=issued,
        expires_at=issued + timedelta(minutes=15),
        grants=tuple(grants),
    )


def test_snapshot_separates_plan_name_from_machine_entitlements() -> None:
    snapshot = _snapshot(
        EntitlementGrant(key="chat.access", allowed=True),
        EntitlementGrant(key="model.explicit_selection", allowed=False),
        EntitlementGrant(key="files.count", allowed=True, limit=25),
    )

    assert snapshot.allows("chat.access") is True
    assert snapshot.allows("model.explicit_selection") is False
    assert snapshot.allows("unknown.feature") is False
    assert snapshot.resolve("files.count").limit == 25

    public = snapshot.to_policy_dict()
    serialized = repr(public).lower()
    for forbidden in (
        "plan_name",
        "subscription",
        "payment",
        "provider_secret",
        "credential",
    ):
        assert forbidden not in serialized


def test_snapshot_is_product_and_subject_scoped() -> None:
    snapshot = _snapshot(EntitlementGrant(key="web.search", allowed=True))
    public = snapshot.to_policy_dict()

    assert public["product_id"] == "padiem-chat"
    assert public["subject"] == {
        "subject_type": "user",
        "subject_id": "usr_canonical_001",
    }
    assert public["revision"] == "rev_001"


def test_duplicate_entitlement_keys_fail_closed() -> None:
    with pytest.raises(ControlPlaneContractError) as exc_info:
        _snapshot(
            EntitlementGrant(key="chat.access", allowed=True),
            EntitlementGrant(key="chat.access", allowed=False),
        )
    assert exc_info.value.code == "duplicate_entitlement"


def test_denied_grant_cannot_carry_positive_limit() -> None:
    with pytest.raises(ControlPlaneContractError) as exc_info:
        EntitlementGrant(key="files.count", allowed=False, limit=1)
    assert exc_info.value.code == "invalid_entitlement"


def test_snapshot_requires_bounded_server_timestamps() -> None:
    aware = datetime(2026, 8, 30, 11, 30, tzinfo=timezone.utc)
    subject = CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id="usr_001")

    with pytest.raises(ControlPlaneContractError):
        EntitlementSnapshot(
            snapshot_id="ent_snap_naive",
            product_id="padiem-chat",
            subject=subject,
            revision="rev_001",
            issued_at=datetime(2026, 8, 30, 11, 30),
            expires_at=aware + timedelta(minutes=15),
            grants=(),
        )

    with pytest.raises(ControlPlaneContractError):
        EntitlementSnapshot(
            snapshot_id="ent_snap_expired",
            product_id="padiem-chat",
            subject=subject,
            revision="rev_001",
            issued_at=aware,
            expires_at=aware,
            grants=(),
        )
