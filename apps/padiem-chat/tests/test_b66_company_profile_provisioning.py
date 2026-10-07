"""Tests for trusted server-only B66 CompanyProfile provisioning (#3406)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.b66_company_profile_provisioning import B66CompanyProfileProvisioner
from app.b66_quote_skill_provisioning import (
    B66ProvisioningAction,
    B66ProvisioningError,
    ResolvedB66ProvisioningTarget,
    TrustedB66ProvisioningGrant,
)
from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType

NOW = datetime(2026, 10, 3, 9, 0, tzinfo=timezone.utc)


def _grant(*actions):
    return TrustedB66ProvisioningGrant(
        grant_ref="grant:b66:company:test",
        operator_subject=CanonicalSubjectRef(
            SubjectType.USER, "operator_company_subject"
        ),
        authority_ref="authority:b66:ops",
        allowed_actions=tuple(
            actions or (B66ProvisioningAction.PROVISION_COMPANY_PROFILE,)
        ),
        issued_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(minutes=30),
    )
def _target():
    return ResolvedB66ProvisioningTarget(
        user_id="usr_" + "a" * 32,
        workspace_id="workspace_company_owner",
        tenant_id="tenant_" + "b" * 32,
        canonical_subject_id="subject_company_customer",
    )


class _Store:
    def __init__(self):
        self.calls = []

    async def put_profile(self, *, user_id, workspace_id, profile):
        self.calls.append((user_id, workspace_id, dict(profile)))
        return {**profile, "updatedAt": "2026-10-03T09:00:00Z"}


@pytest.mark.asyncio
async def test_operator_provisions_only_reviewed_fields_and_receipt_has_no_values():
    store = _Store()
    provisioner = B66CompanyProfileProvisioner(store)
    stored, receipt = await provisioner.provision(
        grant=_grant(),
        target=_target(),
        profile={
            "company": "Synthetic Company",
            "representative": "Synthetic Rep",
            "phone": "000-0000-0000",
        },
        now=NOW,
    )
    assert stored["company"] == "Synthetic Company"
    call = store.calls[0]
    assert call[0] == "usr_" + "a" * 32
    assert call[1] == "workspace_company_owner"
    assert call[2]["defaultValidityDays"] is None
    assert call[2]["defaultTaxMode"] is None

    safe = receipt.safe_dict()
    assert safe["action"] == "provision_company_profile"
    assert safe["provisioned_fields"] == ["company", "representative", "phone"]
    serialized = repr(safe)
    assert "Synthetic Company" not in serialized
    assert "Synthetic Rep" not in serialized
    assert "000-0000-0000" not in serialized


@pytest.mark.asyncio
async def test_unreviewed_defaults_are_not_invented():
    store = _Store()
    provisioner = B66CompanyProfileProvisioner(store)
    stored, _ = await provisioner.provision(
        grant=_grant(),
        target=_target(),
        profile={"company": "Synthetic Company"},
        now=NOW,
    )
    assert stored["defaultValidityDays"] is None
    assert stored["defaultTaxMode"] is None
@pytest.mark.asyncio
async def test_wrong_action_or_raw_target_is_rejected_before_store():
    store = _Store()
    provisioner = B66CompanyProfileProvisioner(store)

    with pytest.raises(B66ProvisioningError, match="not authorized"):
        await provisioner.provision(
            grant=_grant(B66ProvisioningAction.ASSIGN),
            target=_target(),
            profile={"company": "Synthetic Company"},
            now=NOW,
        )

    with pytest.raises(B66ProvisioningError, match="server-resolved target"):
        await provisioner.provision(
            grant=_grant(),
            target={"user_id": "forged"},  # type: ignore[arg-type]
            profile={"company": "Synthetic Company"},
            now=NOW,
        )

    assert store.calls == []
