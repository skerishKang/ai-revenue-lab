from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any

from .contracts import ContractError
from .ops_delivery import (
    ConnectorBinding,
    ManagedOnboardingProjection,
    ModelCredentialMode,
    OpsDeliveryMode,
    OpsExecutionProfile,
)
from .security import redact_secrets

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")


def _ref(value: str | None, field_name: str, *, required: bool = True) -> str | None:
    if value is None:
        if required:
            raise ContractError(f"{field_name} is required")
        return None
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    value = value.strip()
    if redact_secrets(value) != value:
        raise ContractError(f"{field_name} must not contain credential material")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class TrustedAccountSessionProjection:
    session_ref: str
    account_ref: str
    issued_at: datetime
    expires_at: datetime
    authority_ref: str

    def __post_init__(self) -> None:
        for name in ("session_ref", "account_ref", "authority_ref"):
            object.__setattr__(self, name, _ref(getattr(self, name), name))
        issued = _aware(self.issued_at, "issued_at")
        expires = _aware(self.expires_at, "expires_at")
        if expires <= issued:
            raise ContractError("session expires_at must follow issued_at")
        object.__setattr__(self, "issued_at", issued)
        object.__setattr__(self, "expires_at", expires)

    def require_active(self, now: datetime) -> None:
        now = _aware(now, "now")
        if now < self.issued_at or now >= self.expires_at:
            raise ContractError("trusted account session is not currently active")


@dataclass(frozen=True, slots=True)
class TrustedWorkspaceEntitlementProjection:
    entitlement_ref: str
    account_ref: str
    workspace_id: str
    org_ref: str | None
    managed_cloud_allowed: bool
    issued_at: datetime
    expires_at: datetime
    authority_ref: str

    def __post_init__(self) -> None:
        for name in ("entitlement_ref", "account_ref", "workspace_id", "authority_ref"):
            object.__setattr__(self, name, _ref(getattr(self, name), name))
        object.__setattr__(self, "org_ref", _ref(self.org_ref, "org_ref", required=False))
        if not isinstance(self.managed_cloud_allowed, bool):
            raise ContractError("managed_cloud_allowed must be boolean")
        issued = _aware(self.issued_at, "issued_at")
        expires = _aware(self.expires_at, "expires_at")
        if expires <= issued:
            raise ContractError("entitlement expires_at must follow issued_at")
        object.__setattr__(self, "issued_at", issued)
        object.__setattr__(self, "expires_at", expires)

    def require_active(self, now: datetime) -> None:
        now = _aware(now, "now")
        if now < self.issued_at or now >= self.expires_at:
            raise ContractError("trusted workspace entitlement is not currently active")
        if not self.managed_cloud_allowed:
            raise ContractError("workspace entitlement does not allow Managed Cloud")


@dataclass(frozen=True, slots=True)
class ManagedOnboardingResult:
    profile: OpsExecutionProfile
    projection: ManagedOnboardingProjection
    session_ref: str
    entitlement_ref: str

    def safe_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile.safe_dict(),
            "projection": self.projection.safe_dict(),
            "session_ref": self.session_ref,
            "entitlement_ref": self.entitlement_ref,
            "managed_default": True,
            "raw_provider_key_input": False,
            "oauth_implemented_here": False,
            "billing_authority": False,
            "membership_authority": False,
        }


class ManagedClawOnboardingService:
    def build(
        self,
        *,
        session: TrustedAccountSessionProjection,
        entitlement: TrustedWorkspaceEntitlementProjection,
        now: datetime,
        connectors: tuple[ConnectorBinding, ...] = (),
        supplier_count: int = 0,
    ) -> ManagedOnboardingResult:
        if not isinstance(session, TrustedAccountSessionProjection):
            raise ContractError("trusted account session projection is required")
        if not isinstance(entitlement, TrustedWorkspaceEntitlementProjection):
            raise ContractError("trusted workspace entitlement projection is required")
        session.require_active(now)
        entitlement.require_active(now)
        if session.account_ref != entitlement.account_ref:
            raise ContractError("session and workspace entitlement account mismatch")
        if not isinstance(connectors, tuple) or not all(isinstance(item, ConnectorBinding) for item in connectors):
            raise ContractError("connectors must be trusted ConnectorBinding values")
        if isinstance(supplier_count, bool) or not isinstance(supplier_count, int) or not 0 <= supplier_count <= 1_000_000:
            raise ContractError("supplier_count must be a bounded non-negative integer")
        profile = OpsExecutionProfile(
            workspace_id=entitlement.workspace_id,
            account_ref=session.account_ref,
            org_ref=entitlement.org_ref,
            delivery_mode=OpsDeliveryMode.CLOUD_MANAGED,
            model_credential_mode=ModelCredentialMode.PADIEM_MANAGED,
            entitlement_ref=entitlement.entitlement_ref,
            model_secret_ref=None,
            connectors=connectors,
        )
        projection = ManagedOnboardingProjection(
            account_ref=session.account_ref,
            workspace_id=entitlement.workspace_id,
            supplier_count=supplier_count,
            connector_count=sum(1 for item in connectors if item.enabled),
        )
        return ManagedOnboardingResult(
            profile=profile,
            projection=projection,
            session_ref=session.session_ref,
            entitlement_ref=entitlement.entitlement_ref,
        )


CLIENT_ASSERTED_ENTITLEMENT_SUPPORTED = False
RAW_PROVIDER_KEY_INPUT_SUPPORTED = False
OAUTH_IMPLEMENTED_IN_B54 = False
BILLING_AUTHORITY_IN_B54 = False
