"""Trusted server-only B66 private quote asset provisioning (#3427).

This module exposes no HTTP/browser route. A trusted host must supply the
existing B66 operator grant and a server-resolved account/workspace target.
Asset bytes are passed only to the existing private B66QuoteAssetStore, which
owns media/size validation, R2 object-key minting, and metadata persistence.
"""

from __future__ import annotations

import inspect
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .b66_quote_assets import B66QuoteAssetMetadata
from .b66_quote_skill_provisioning import (
    B66ProvisioningAction,
    B66ProvisioningError,
    ResolvedB66ProvisioningTarget,
    TrustedB66ProvisioningGrant,
)


@dataclass(frozen=True, slots=True)
class B66AssetProvisioningReceipt:
    receipt_ref: str
    grant_ref: str
    operator_subject_id: str
    target_tenant_id: str
    target_workspace_id: str
    target_user_id: str
    asset_id: str
    asset_kind: str
    media_type: str
    byte_length: int
    sha256: str
    occurred_at: datetime

    def safe_dict(self) -> dict[str, object]:
        return {
            "receipt_ref": self.receipt_ref,
            "action": B66ProvisioningAction.PROVISION_ASSET.value,
            "grant_ref": self.grant_ref,
            "operator_subject_id": self.operator_subject_id,
            "target_tenant_id": self.target_tenant_id,
            "target_workspace_id": self.target_workspace_id,
            "target_user_id": self.target_user_id,
            "asset_id": self.asset_id,
            "asset_kind": self.asset_kind,
            "media_type": self.media_type,
            "byte_length": self.byte_length,
            "sha256": self.sha256,
            "occurred_at": self.occurred_at.isoformat(),
        }


def _receipt_ref() -> str:
    return "b66assetprov_" + uuid.uuid4().hex


def _checked_now(value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise B66ProvisioningError("now must be timezone-aware")
    return value.astimezone(timezone.utc)


class B66QuoteAssetProvisioner:
    """Bounded trusted-host command over the existing private asset store."""

    def __init__(self, store: Any):
        put_fn = getattr(store, "put_approved_asset", None)
        if not callable(put_fn):
            raise ValueError("B66 quote asset store is required")
        self._store = store

    @staticmethod
    def _authorize(
        *,
        grant: TrustedB66ProvisioningGrant,
        target: ResolvedB66ProvisioningTarget,
        now: datetime,
    ) -> tuple[ResolvedB66ProvisioningTarget, datetime]:
        if not isinstance(grant, TrustedB66ProvisioningGrant):
            raise B66ProvisioningError("trusted operator grant is required")
        if not isinstance(target, ResolvedB66ProvisioningTarget):
            raise B66ProvisioningError("server-resolved target is required")
        checked = _checked_now(now)
        action = B66ProvisioningAction.PROVISION_ASSET
        if not grant.is_active(now=checked) or not grant.allows(action):
            raise B66ProvisioningError("operator is not authorized")
        return target, checked

    async def provision(
        self,
        *,
        grant: TrustedB66ProvisioningGrant,
        target: ResolvedB66ProvisioningTarget,
        asset_kind: str,
        media_type: str,
        body: bytes,
        now: datetime,
    ) -> tuple[B66QuoteAssetMetadata, B66AssetProvisioningReceipt]:
        resolved, checked = self._authorize(
            grant=grant,
            target=target,
            now=now,
        )
        value = self._store.put_approved_asset(
            user_id=resolved.user_id,
            workspace_id=resolved.workspace_id,
            asset_kind=asset_kind,
            media_type=media_type,
            body=body,
        )
        metadata = await value if inspect.isawaitable(value) else value
        if not isinstance(metadata, B66QuoteAssetMetadata):
            raise B66ProvisioningError(
                "private asset store did not return canonical metadata"
            )
        receipt = B66AssetProvisioningReceipt(
            receipt_ref=_receipt_ref(),
            grant_ref=grant.grant_ref,
            operator_subject_id=grant.operator_subject.subject_id,
            target_tenant_id=resolved.tenant_id,
            target_workspace_id=resolved.workspace_id,
            target_user_id=resolved.user_id,
            asset_id=metadata.asset_id,
            asset_kind=metadata.asset_kind,
            media_type=metadata.media_type,
            byte_length=metadata.byte_length,
            sha256=metadata.sha256,
            occurred_at=checked,
        )
        return metadata, receipt


__all__ = [
    "B66AssetProvisioningReceipt",
    "B66QuoteAssetProvisioner",
]
