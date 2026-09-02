from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any

from .contracts import ContractError
from .integration_readiness import (
    IntegrationReadinessDecision,
    LiveCapability,
    TrustedAdapterProbe,
    evaluate_live_capability,
)
from .managed_onboarding import (
    ManagedOnboardingResult,
    TrustedAccountSessionProjection,
    TrustedWorkspaceEntitlementProjection,
)
from .ops_delivery import ModelCredentialMode, OpsDeliveryMode
from .security import redact_secrets


_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")


def _ref(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    value = value.strip()
    if redact_secrets(value) != value:
        raise ContractError(f"{field_name} must not contain credential material")
    return value


@dataclass(frozen=True, slots=True)
class TrustedScopedAdapterProbe:
    """Trusted binding of an existing adapter probe to one deployment scope.

    The wrapped probe remains the source of adapter connectivity/freshness facts.
    This wrapper adds only trusted environment/deployment correlation and must not
    contain an endpoint, credential, or provider-specific secret.
    """

    probe: TrustedAdapterProbe
    environment_ref: str
    deployment_ref: str
    scope_authority_ref: str
    scope_evidence_ref: str

    def __post_init__(self) -> None:
        if not isinstance(self.probe, TrustedAdapterProbe):
            raise ContractError("probe must be TrustedAdapterProbe")
        for field_name in (
            "environment_ref",
            "deployment_ref",
            "scope_authority_ref",
            "scope_evidence_ref",
        ):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "probe_id": self.probe.probe_id,
            "adapter_kind": self.probe.adapter_kind.value,
            "state": self.probe.state.value,
            "environment_ref": self.environment_ref,
            "deployment_ref": self.deployment_ref,
            "scope_authority_ref": self.scope_authority_ref,
            "scope_evidence_ref": self.scope_evidence_ref,
            "probe_evidence_ref": self.probe.evidence_ref,
            "endpoint": None,
            "credential": None,
        }


@dataclass(frozen=True, slots=True)
class ManagedLivePreflightDecision:
    environment_ref: str
    deployment_ref: str
    account_ref: str
    workspace_id: str
    entitlement_ref: str
    capability: LiveCapability
    readiness: IntegrationReadinessDecision
    scoped_probe_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "environment_ref",
            "deployment_ref",
            "account_ref",
            "workspace_id",
            "entitlement_ref",
        ):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        if not isinstance(self.capability, LiveCapability):
            raise ContractError("capability must be LiveCapability")
        if not isinstance(self.readiness, IntegrationReadinessDecision):
            raise ContractError("readiness must be IntegrationReadinessDecision")
        if self.readiness.capability is not self.capability:
            raise ContractError("readiness capability mismatch")
        if not isinstance(self.scoped_probe_ids, tuple):
            raise ContractError("scoped_probe_ids must be a tuple")
        normalized = tuple(_ref(item, "scoped_probe_id") for item in self.scoped_probe_ids)
        if len(set(normalized)) != len(normalized):
            raise ContractError("scoped_probe_ids must be unique")
        object.__setattr__(self, "scoped_probe_ids", normalized)

    @property
    def live_ready(self) -> bool:
        return self.readiness.live_configured

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-managed-live-preflight.v1",
            "environment_ref": self.environment_ref,
            "deployment_ref": self.deployment_ref,
            "account_ref": self.account_ref,
            "workspace_id": self.workspace_id,
            "entitlement_ref": self.entitlement_ref,
            "capability": self.capability.value,
            "live_ready": self.live_ready,
            "scoped_probe_ids": list(self.scoped_probe_ids),
            "readiness": self.readiness.safe_dict(),
            "environment_scoped": True,
            "fresh_identity_entitlement_required": True,
            "security_certification": False,
            "deployment_approval": False,
            "endpoint": None,
            "credential": None,
        }


def evaluate_managed_live_preflight(
    *,
    onboarding: ManagedOnboardingResult,
    session: TrustedAccountSessionProjection,
    entitlement: TrustedWorkspaceEntitlementProjection,
    scoped_probes: tuple[TrustedScopedAdapterProbe, ...],
    capability: LiveCapability,
    environment_ref: str,
    deployment_ref: str,
    now: datetime,
) -> ManagedLivePreflightDecision:
    if not isinstance(onboarding, ManagedOnboardingResult):
        raise ContractError("onboarding must be ManagedOnboardingResult")
    if not isinstance(session, TrustedAccountSessionProjection):
        raise ContractError("session must be TrustedAccountSessionProjection")
    if not isinstance(entitlement, TrustedWorkspaceEntitlementProjection):
        raise ContractError("entitlement must be TrustedWorkspaceEntitlementProjection")
    if not isinstance(scoped_probes, tuple) or not all(
        isinstance(item, TrustedScopedAdapterProbe) for item in scoped_probes
    ):
        raise ContractError("scoped_probes must be a tuple of TrustedScopedAdapterProbe")
    if not isinstance(capability, LiveCapability):
        try:
            capability = LiveCapability(capability)
        except (TypeError, ValueError) as exc:
            raise ContractError("invalid live capability") from exc

    environment_ref = _ref(environment_ref, "environment_ref")
    deployment_ref = _ref(deployment_ref, "deployment_ref")

    # Onboarding can be older than execution. Re-check the trusted authorities at
    # the moment of live preflight instead of trusting the prior projection alone.
    session.require_active(now)
    entitlement.require_active(now)
    if session.account_ref != entitlement.account_ref:
        raise ContractError("session and entitlement account mismatch")

    profile = onboarding.profile
    projection = onboarding.projection
    if profile.delivery_mode is not OpsDeliveryMode.CLOUD_MANAGED:
        raise ContractError("Managed live preflight requires Cloud Managed profile")
    if profile.model_credential_mode is not ModelCredentialMode.PADIEM_MANAGED:
        raise ContractError("Managed live preflight requires Padiem-managed credential mode")
    if profile.model_secret_ref is not None:
        raise ContractError("Managed live preflight cannot carry a model secret reference")
    if onboarding.session_ref != session.session_ref:
        raise ContractError("onboarding session correlation mismatch")
    if onboarding.entitlement_ref != entitlement.entitlement_ref:
        raise ContractError("onboarding entitlement correlation mismatch")
    if profile.account_ref != session.account_ref:
        raise ContractError("onboarding account correlation mismatch")
    if profile.workspace_id != entitlement.workspace_id:
        raise ContractError("onboarding workspace correlation mismatch")
    if profile.entitlement_ref != entitlement.entitlement_ref:
        raise ContractError("execution profile entitlement correlation mismatch")
    if projection.account_ref != session.account_ref:
        raise ContractError("onboarding projection account correlation mismatch")
    if projection.workspace_id != entitlement.workspace_id:
        raise ContractError("onboarding projection workspace correlation mismatch")

    exact_scope = tuple(
        item
        for item in scoped_probes
        if item.environment_ref == environment_ref and item.deployment_ref == deployment_ref
    )
    readiness = evaluate_live_capability(
        probes=tuple(item.probe for item in exact_scope),
        capability=capability,
        now=now,
    )
    return ManagedLivePreflightDecision(
        environment_ref=environment_ref,
        deployment_ref=deployment_ref,
        account_ref=session.account_ref,
        workspace_id=entitlement.workspace_id,
        entitlement_ref=entitlement.entitlement_ref,
        capability=capability,
        readiness=readiness,
        scoped_probe_ids=tuple(sorted(item.probe.probe_id for item in exact_scope)),
    )


PRODUCTION_READINESS_REQUIRES_SCOPED_PROBES = True
SECURITY_CERTIFICATION_FROM_PREFLIGHT = False
DEPLOYMENT_APPROVAL_FROM_PREFLIGHT = False
