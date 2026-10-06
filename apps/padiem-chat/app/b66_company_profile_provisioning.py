"""Trusted server-only B66 CompanyProfile provisioning (#3406).

No browser route is exposed here. The host must supply the existing trusted B66
operator grant plus a server-resolved account/workspace target. Real company
values are runtime input and are never copied into receipts.
"""

from __future__ import annotations

import inspect
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .b66_company_profile import CompanyProfileError, canonicalize_company_profile
from .b66_quote_skill_provisioning import (
    B66ProvisioningAction,
    B66ProvisioningError,
    ResolvedB66ProvisioningTarget,
    TrustedB66ProvisioningGrant,
)


@dataclass(frozen=True, slots=True)
class B66CompanyProfileProvisioningReceipt:
    receipt_ref: str
    grant_ref: str
    operator_subject_id: str
    target_tenant_id: str
    target_workspace_id: str
    target_user_id: str
    provisioned_fields: tuple[str, ...]
    occurred_at: datetime
    def safe_dict(self) -> dict[str, object]:
        return {
            "receipt_ref": self.receipt_ref,
            "action": B66ProvisioningAction.PROVISION_COMPANY_PROFILE.value,
            "grant_ref": self.grant_ref,
            "operator_subject_id": self.operator_subject_id,
            "target_tenant_id": self.target_tenant_id,
            "target_workspace_id": self.target_workspace_id,
            "target_user_id": self.target_user_id,
            "provisioned_fields": list(self.provisioned_fields),
            "occurred_at": self.occurred_at.isoformat(),
        }


def _receipt_ref() -> str:
    return "b66companyprov_" + uuid.uuid4().hex


def _checked_now(value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise B66ProvisioningError("now must be timezone-aware")
    return value.astimezone(timezone.utc)
class B66CompanyProfileProvisioner:
    def __init__(self, store: Any):
        put_fn = getattr(store, "put_profile", None)
        if not callable(put_fn):
            raise ValueError("B66 company profile store is required")
        self._store = store

    async def provision(
        self,
        *,
        grant: TrustedB66ProvisioningGrant,
        target: ResolvedB66ProvisioningTarget,
        profile: dict[str, Any],
        now: datetime,
    ) -> tuple[dict[str, Any], B66CompanyProfileProvisioningReceipt]:
        if not isinstance(grant, TrustedB66ProvisioningGrant):
            raise B66ProvisioningError("trusted operator grant is required")
        if not isinstance(target, ResolvedB66ProvisioningTarget):
            raise B66ProvisioningError("server-resolved target is required")
        checked = _checked_now(now)
        action = B66ProvisioningAction.PROVISION_COMPANY_PROFILE
        if not grant.is_active(now=checked) or not grant.allows(action):
            raise B66ProvisioningError("operator is not authorized")

        try:
            canonical = canonicalize_company_profile(profile)
        except CompanyProfileError as exc:
            raise B66ProvisioningError("company profile is invalid") from exc
        value = self._store.put_profile(
            user_id=target.user_id,
            workspace_id=target.workspace_id,
            profile=canonical,
        )
        stored = await value if inspect.isawaitable(value) else value
        if not isinstance(stored, dict):
            raise B66ProvisioningError("company profile store did not return a profile")

        provisioned_fields = tuple(
            key for key, item in canonical.items() if item is not None
        )
        receipt = B66CompanyProfileProvisioningReceipt(
            receipt_ref=_receipt_ref(),
            grant_ref=grant.grant_ref,
            operator_subject_id=grant.operator_subject.subject_id,
            target_tenant_id=target.tenant_id,
            target_workspace_id=target.workspace_id,
            target_user_id=target.user_id,
            provisioned_fields=provisioned_fields,
            occurred_at=checked,
        )
        return stored, receipt


__all__ = [
    "B66CompanyProfileProvisioner",
    "B66CompanyProfileProvisioningReceipt",
]
