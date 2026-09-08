"""Managed Cloud onboarding projection contract for the Control Plane (#1563).

Promoted-lane projection of the reviewed B54 onboarding composition
(``apps/korean-ai-code-agent/src/kagent/managed_onboarding.py`` together
with its structural dependencies in ``ops_delivery.py``). A
trusted account session plus a trusted workspace entitlement (plus
optional trusted connector bindings) compose into exactly one Managed
Cloud execution profile and one onboarding projection for handoff.

This module owns only the onboarding-composition mechanics:

- ``TrustedAccountSessionProjection``: session/account refs, issued and
  expiry bounds, authority ref, active-window check,
- ``TrustedWorkspaceEntitlementProjection``: entitlement/account/
  workspace refs, optional org ref, Managed-Cloud allow flag, issued and
  expiry bounds, authority ref, active-window check,
- ``SecretReference`` / ``ConnectorBinding``: opaque bounded credential
  and connector refs only — raw provider keys are rejected at the
  boundary, never stored,
- ``OpsExecutionProfile`` with delivery/credential mode cross-checks:
  Cloud Managed is server-owned default and requires Padiem-managed
  model credentials, no model secret ref and a trusted entitlement ref,
- ``ManagedOnboardingProjection`` with its readiness status,
- ``ManagedCloudOnboardingService.build``: exact account correlation
  between session and entitlement, active-window checks, bounded
  connector tuple and bounded supplier count.

It deliberately does NOT own:

- membership, billing, pricing, credit, OAuth, secret storage,
  provider routing or sandbox authority of any kind,
- raw provider API keys: the ``sk-``/``bearer``/``api_key=``-style
  prefix rejection is enforced on every reference;
- runtime execution, network calls, database reads or Production
  mutation: composition is pure offline validation;
- client assertions: entitlement refs come only from trusted
  projections, never from client input.

No authority is ever minted from an onboarding result.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any

from .contracts import ControlPlaneContractError

MAX_SUPPLIER_COUNT = 1_000_000
MAX_CONNECTORS = 32

# Honest capability flags (ported from the reviewed contract):
# this lane performs onboarding composition only.
CLIENT_ASSERTED_ENTITLEMENT_SUPPORTED = False
RAW_PROVIDER_KEY_INPUT_SUPPORTED = False
OAUTH_IMPLEMENTED_HERE = False
BILLING_AUTHORITY = False
MEMBERSHIP_AUTHORITY = False

# Trusted-projection refs (ported from managed_onboarding.py).
_PROJECTION_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")
# Delivery-domain refs (ported from ops_delivery.py).
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
# Deterministic half of the scaffold's raw-secret rejection (CP has no
# redact_secrets helper, same recorded deviation as #1572/#1556).
_SECRET_PREFIXES = ("sk-", "bearer ", "api_key=", "apikey=", "token=", "secret=", "password=")

_S = "invalid_account_session"
_E = "invalid_workspace_entitlement"
_C = "invalid_connector_binding"
_X = "invalid_secret_reference"
_P = "invalid_execution_profile"
_O = "invalid_onboarding_projection"
_M = "onboarding_account_mismatch"


def _projection_ref(value: str | None, field_name: str, *, required: bool = True, code: str) -> str | None:
    if value is None:
        if required:
            raise ControlPlaneContractError(code, f"{field_name} is required")
        return None
    if not isinstance(value, str) or not _PROJECTION_REF_RE.fullmatch(value.strip()):
        raise ControlPlaneContractError(code, f"{field_name} must be a bounded safe reference")
    return value.strip()


def _ref(value: str | None, field_name: str, *, required: bool = True, code: str) -> str | None:
    if value is None:
        if required:
            raise ControlPlaneContractError(code, f"{field_name} is required")
        return None
    if not isinstance(value, str):
        raise ControlPlaneContractError(code, f"{field_name} must be a string")
    value = value.strip()
    if not value:
        if required:
            raise ControlPlaneContractError(code, f"{field_name} is required")
        return None
    if not _REF_RE.fullmatch(value):
        raise ControlPlaneContractError(code, f"{field_name} must be a bounded safe reference")
    if value.lower().startswith(_SECRET_PREFIXES):
        raise ControlPlaneContractError(code, f"{field_name} must be an opaque reference, never a raw secret")
    return value


def _aware(value: datetime, field_name: str, *, code: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ControlPlaneContractError(code, f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _bounded_tuple(value: tuple[Any, ...], field_name: str, *, maximum: int, code: str) -> tuple[Any, ...]:
    if not isinstance(value, tuple) or len(value) > maximum:
        raise ControlPlaneContractError(code, f"{field_name} must be a tuple with at most {maximum} entries")
    return value


class OpsDeliveryMode(str, Enum):
    """Execution delivery modes accepted by the onboarding composition."""

    CLOUD_MANAGED = "cloud_managed"
    CLOUD_BYOK = "cloud_byok"
    LOCAL = "local"
    SELF_HOSTED = "self_hosted"


class ModelCredentialMode(str, Enum):
    """Model-credential modes accepted by the onboarding composition."""

    PADIEM_MANAGED = "padiem_managed"
    SECRET_REFERENCE = "secret_reference"
    LOCAL_OR_SELF_HOSTED = "local_or_self_hosted"


class OnboardingStatus(str, Enum):
    """Readiness status derived from an onboarding projection."""

    ACCOUNT_REQUIRED = "account_required"
    WORKSPACE_REQUIRED = "workspace_required"
    CONNECTORS_OPTIONAL = "connectors_optional"
    READY = "ready"


@dataclass(frozen=True, slots=True)
class SecretReference:
    """One opaque secret reference (never a raw secret value)."""

    secret_ref: str
    purpose: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "secret_ref", _ref(self.secret_ref, "secret_ref", code=_X))
        purpose = _ref(self.purpose, "purpose", code=_X)
        assert purpose is not None
        object.__setattr__(self, "purpose", purpose)

    def safe_dict(self) -> dict[str, str]:
        return {"secret_ref": self.secret_ref, "purpose": self.purpose}


@dataclass(frozen=True, slots=True)
class ConnectorBinding:
    """One trusted connector binding with an opaque credential ref."""

    connector_id: str
    account_ref: str
    credential_ref: SecretReference
    enabled: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "connector_id", _ref(self.connector_id, "connector_id", code=_C))
        object.__setattr__(self, "account_ref", _ref(self.account_ref, "account_ref", code=_C))
        if not isinstance(self.credential_ref, SecretReference):
            raise ControlPlaneContractError(_C, "credential_ref must be SecretReference")
        if not isinstance(self.enabled, bool):
            raise ControlPlaneContractError(_C, "enabled must be boolean")


@dataclass(frozen=True, slots=True)
class OpsExecutionProfile:
    """The server-owned execution profile handed off by onboarding.

    Cloud Managed is the server-owned default path used by the onboarding
    builder: Padiem-managed model credentials, no model secret ref, and a
    trusted entitlement ref are all required together.
    """

    workspace_id: str
    account_ref: str
    org_ref: str | None
    delivery_mode: OpsDeliveryMode
    model_credential_mode: ModelCredentialMode
    entitlement_ref: str | None = None
    model_secret_ref: SecretReference | None = None
    connectors: tuple[ConnectorBinding, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace_id", _ref(self.workspace_id, "workspace_id", code=_P))
        object.__setattr__(self, "account_ref", _ref(self.account_ref, "account_ref", code=_P))
        object.__setattr__(self, "org_ref", _ref(self.org_ref, "org_ref", required=False, code=_P))
        if not isinstance(self.delivery_mode, OpsDeliveryMode):
            try:
                object.__setattr__(self, "delivery_mode", OpsDeliveryMode(self.delivery_mode))
            except (TypeError, ValueError) as exc:
                raise ControlPlaneContractError(_P, "invalid delivery_mode") from exc
        if not isinstance(self.model_credential_mode, ModelCredentialMode):
            try:
                object.__setattr__(self, "model_credential_mode", ModelCredentialMode(self.model_credential_mode))
            except (TypeError, ValueError) as exc:
                raise ControlPlaneContractError(_P, "invalid model_credential_mode") from exc
        object.__setattr__(self, "entitlement_ref", _ref(self.entitlement_ref, "entitlement_ref", required=False, code=_P))
        if self.model_secret_ref is not None and not isinstance(self.model_secret_ref, SecretReference):
            raise ControlPlaneContractError(_P, "model_secret_ref must be SecretReference or None")
        _bounded_tuple(self.connectors, "connectors", maximum=MAX_CONNECTORS, code=_P)
        if not all(isinstance(item, ConnectorBinding) for item in self.connectors):
            raise ControlPlaneContractError(_P, "connectors must contain ConnectorBinding values")
        if len({item.connector_id for item in self.connectors}) != len(self.connectors):
            raise ControlPlaneContractError(_P, "connector_id values must be unique")

        mode = self.delivery_mode
        credential_mode = self.model_credential_mode
        if mode is OpsDeliveryMode.CLOUD_MANAGED:
            if credential_mode is not ModelCredentialMode.PADIEM_MANAGED:
                raise ControlPlaneContractError(_P, "Cloud Managed must use Padiem-managed model credentials")
            if self.model_secret_ref is not None:
                raise ControlPlaneContractError(_P, "Cloud Managed profile must not carry a model secret reference")
            if self.entitlement_ref is None:
                raise ControlPlaneContractError(_P, "Cloud Managed requires a trusted entitlement reference")
        elif mode is OpsDeliveryMode.CLOUD_BYOK:
            if credential_mode is not ModelCredentialMode.SECRET_REFERENCE:
                raise ControlPlaneContractError(_P, "Cloud BYOK requires secret-reference credential mode")
            if self.model_secret_ref is None:
                raise ControlPlaneContractError(_P, "Cloud BYOK requires an opaque model secret reference")
        elif mode in {OpsDeliveryMode.LOCAL, OpsDeliveryMode.SELF_HOSTED}:
            if credential_mode not in {
                ModelCredentialMode.SECRET_REFERENCE,
                ModelCredentialMode.LOCAL_OR_SELF_HOSTED,
            }:
                raise ControlPlaneContractError(_P, "Local/Self-Hosted cannot claim Padiem-managed credential authority")

    @property
    def requires_user_provider_key_input(self) -> bool:
        return self.delivery_mode is OpsDeliveryMode.CLOUD_BYOK

    @property
    def dedicated_ai_workstation_required(self) -> bool:
        return False

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-ops-execution-profile.v1",
            "workspace_id": self.workspace_id,
            "account_ref": self.account_ref,
            "org_ref": self.org_ref,
            "delivery_mode": self.delivery_mode.value,
            "model_credential_mode": self.model_credential_mode.value,
            "entitlement_ref": self.entitlement_ref,
            "model_secret_ref": self.model_secret_ref.safe_dict() if self.model_secret_ref else None,
            "connectors": [
                {
                    "connector_id": item.connector_id,
                    "account_ref": item.account_ref,
                    "credential_ref": item.credential_ref.safe_dict(),
                    "enabled": item.enabled,
                }
                for item in self.connectors
            ],
            "requires_user_provider_key_input": self.requires_user_provider_key_input,
            "dedicated_ai_workstation_required": self.dedicated_ai_workstation_required,
        }


@dataclass(frozen=True, slots=True)
class ManagedOnboardingProjection:
    """The bounded onboarding readiness projection for handoff."""

    account_ref: str | None = None
    workspace_id: str | None = None
    supplier_count: int = 0
    connector_count: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "account_ref", _ref(self.account_ref, "account_ref", required=False, code=_O))
        object.__setattr__(self, "workspace_id", _ref(self.workspace_id, "workspace_id", required=False, code=_O))
        for field_name in ("supplier_count", "connector_count"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_SUPPLIER_COUNT:
                raise ControlPlaneContractError(_O, f"{field_name} must be a bounded non-negative integer")

    @property
    def status(self) -> OnboardingStatus:
        if self.account_ref is None:
            return OnboardingStatus.ACCOUNT_REQUIRED
        if self.workspace_id is None:
            return OnboardingStatus.WORKSPACE_REQUIRED
        if self.connector_count == 0:
            return OnboardingStatus.CONNECTORS_OPTIONAL
        return OnboardingStatus.READY

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-ops-onboarding.v1",
            "account_ref": self.account_ref,
            "workspace_id": self.workspace_id,
            "supplier_count": self.supplier_count,
            "connector_count": self.connector_count,
            "status": self.status.value,
            "provider_api_key_required_for_managed": False,
        }


@dataclass(frozen=True, slots=True)
class TrustedAccountSessionProjection:
    """Server-trusted account session projection for one account."""

    session_ref: str
    account_ref: str
    issued_at: datetime
    expires_at: datetime
    authority_ref: str

    def __post_init__(self) -> None:
        for name in ("session_ref", "account_ref", "authority_ref"):
            object.__setattr__(self, name, _projection_ref(getattr(self, name), name, code=_S))
        issued = _aware(self.issued_at, "issued_at", code=_S)
        expires = _aware(self.expires_at, "expires_at", code=_S)
        if expires <= issued:
            raise ControlPlaneContractError(_S, "session expires_at must follow issued_at")
        object.__setattr__(self, "issued_at", issued)
        object.__setattr__(self, "expires_at", expires)

    def require_active(self, now: datetime) -> None:
        now = _aware(now, "now", code=_S)
        if now < self.issued_at or now >= self.expires_at:
            raise ControlPlaneContractError(_S, "trusted account session is not currently active")


@dataclass(frozen=True, slots=True)
class TrustedWorkspaceEntitlementProjection:
    """Server-trusted workspace entitlement projection for one account."""

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
            object.__setattr__(self, name, _projection_ref(getattr(self, name), name, code=_E))
        object.__setattr__(self, "org_ref", _projection_ref(self.org_ref, "org_ref", required=False, code=_E))
        if not isinstance(self.managed_cloud_allowed, bool):
            raise ControlPlaneContractError(_E, "managed_cloud_allowed must be boolean")
        issued = _aware(self.issued_at, "issued_at", code=_E)
        expires = _aware(self.expires_at, "expires_at", code=_E)
        if expires <= issued:
            raise ControlPlaneContractError(_E, "entitlement expires_at must follow issued_at")
        object.__setattr__(self, "issued_at", issued)
        object.__setattr__(self, "expires_at", expires)

    def require_active(self, now: datetime) -> None:
        now = _aware(now, "now", code=_E)
        if now < self.issued_at or now >= self.expires_at:
            raise ControlPlaneContractError(_E, "trusted workspace entitlement is not currently active")
        if not self.managed_cloud_allowed:
            raise ControlPlaneContractError(_E, "workspace entitlement does not allow Managed Cloud")


@dataclass(frozen=True, slots=True)
class ManagedOnboardingResult:
    """The server-owned onboarding result for one account/workspace."""

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


class ManagedCloudOnboardingService:
    """Fail-closed onboarding builder over trusted projections.

    The builder owns only the composition logic.  It performs no network
    calls, no database reads and no Production mutation.
    """

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
            raise ControlPlaneContractError(_S, "trusted account session projection is required")
        if not isinstance(entitlement, TrustedWorkspaceEntitlementProjection):
            raise ControlPlaneContractError(_E, "trusted workspace entitlement projection is required")
        session.require_active(now)
        entitlement.require_active(now)
        if session.account_ref != entitlement.account_ref:
            raise ControlPlaneContractError(_M, "session and workspace entitlement account mismatch")
        if not isinstance(connectors, tuple) or not all(isinstance(item, ConnectorBinding) for item in connectors):
            raise ControlPlaneContractError(_C, "connectors must be trusted ConnectorBinding values")
        if isinstance(supplier_count, bool) or not isinstance(supplier_count, int) or not 0 <= supplier_count <= MAX_SUPPLIER_COUNT:
            raise ControlPlaneContractError(_O, "supplier_count must be a bounded non-negative integer")
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
