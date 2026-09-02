from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any

from .contracts import ContractError
from .security import redact_secrets

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")


def _ref(value: str, field_name: str) -> str:
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


class ExternalAdapterKind(str, Enum):
    CONTROL_PLANE_IDENTITY = "control_plane_identity"
    CONTROL_PLANE_ENTITLEMENT = "control_plane_entitlement"
    B14_MODEL_EXECUTION = "b14_model_execution"
    SANDBOX_PROVIDER = "sandbox_provider"
    GITHUB_REPOSITORY_READ = "github_repository_read"
    GITHUB_DRAFT_WRITE = "github_draft_write"
    COMMUNICATION_OUTBOUND = "communication_outbound"
    ACCOUNTING_READ = "accounting_read"


class ExternalAdapterState(str, Enum):
    UNCONFIGURED = "unconfigured"
    DETERMINISTIC_FAKE = "deterministic_fake"
    CONNECTED = "connected"


class LiveCapability(str, Enum):
    MANAGED_CLOUD_RUN = "managed_cloud_run"
    DRAFT_PR_OUTPUT = "draft_pr_output"
    BUSINESS_MESSAGING = "business_messaging"
    FINANCE_PROJECTION_LIVE_READ = "finance_projection_live_read"


_REQUIRED_ADAPTERS: dict[LiveCapability, frozenset[ExternalAdapterKind]] = {
    LiveCapability.MANAGED_CLOUD_RUN: frozenset(
        {
            ExternalAdapterKind.CONTROL_PLANE_IDENTITY,
            ExternalAdapterKind.CONTROL_PLANE_ENTITLEMENT,
            ExternalAdapterKind.B14_MODEL_EXECUTION,
            ExternalAdapterKind.SANDBOX_PROVIDER,
            ExternalAdapterKind.GITHUB_REPOSITORY_READ,
        }
    ),
    LiveCapability.DRAFT_PR_OUTPUT: frozenset(
        {
            ExternalAdapterKind.CONTROL_PLANE_IDENTITY,
            ExternalAdapterKind.CONTROL_PLANE_ENTITLEMENT,
            ExternalAdapterKind.B14_MODEL_EXECUTION,
            ExternalAdapterKind.SANDBOX_PROVIDER,
            ExternalAdapterKind.GITHUB_REPOSITORY_READ,
            ExternalAdapterKind.GITHUB_DRAFT_WRITE,
        }
    ),
    LiveCapability.BUSINESS_MESSAGING: frozenset(
        {
            ExternalAdapterKind.CONTROL_PLANE_IDENTITY,
            ExternalAdapterKind.CONTROL_PLANE_ENTITLEMENT,
            ExternalAdapterKind.COMMUNICATION_OUTBOUND,
        }
    ),
    LiveCapability.FINANCE_PROJECTION_LIVE_READ: frozenset(
        {
            ExternalAdapterKind.CONTROL_PLANE_IDENTITY,
            ExternalAdapterKind.CONTROL_PLANE_ENTITLEMENT,
            ExternalAdapterKind.ACCOUNTING_READ,
        }
    ),
}


@dataclass(frozen=True, slots=True)
class TrustedAdapterProbe:
    probe_id: str
    adapter_kind: ExternalAdapterKind
    state: ExternalAdapterState
    issued_at: datetime
    expires_at: datetime
    authority_ref: str
    evidence_ref: str

    def __post_init__(self) -> None:
        for name in ("probe_id", "authority_ref", "evidence_ref"):
            object.__setattr__(self, name, _ref(getattr(self, name), name))
        if not isinstance(self.adapter_kind, ExternalAdapterKind):
            try:
                object.__setattr__(self, "adapter_kind", ExternalAdapterKind(self.adapter_kind))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid external adapter kind") from exc
        if not isinstance(self.state, ExternalAdapterState):
            try:
                object.__setattr__(self, "state", ExternalAdapterState(self.state))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid external adapter state") from exc
        issued = _aware(self.issued_at, "issued_at")
        expires = _aware(self.expires_at, "expires_at")
        if expires <= issued:
            raise ContractError("adapter probe expires_at must follow issued_at")
        object.__setattr__(self, "issued_at", issued)
        object.__setattr__(self, "expires_at", expires)

    def connected_at(self, now: datetime) -> bool:
        now = _aware(now, "now")
        return self.state is ExternalAdapterState.CONNECTED and self.issued_at <= now < self.expires_at

    def safe_dict(self) -> dict[str, Any]:
        return {
            "probe_id": self.probe_id,
            "adapter_kind": self.adapter_kind.value,
            "state": self.state.value,
            "issued_at": self.issued_at.isoformat().replace("+00:00", "Z"),
            "expires_at": self.expires_at.isoformat().replace("+00:00", "Z"),
            "authority_ref": self.authority_ref,
            "evidence_ref": self.evidence_ref,
            "endpoint": None,
            "credential": None,
            "security_certification": False,
        }


@dataclass(frozen=True, slots=True)
class IntegrationReadinessDecision:
    capability: LiveCapability
    live_configured: bool
    required_adapters: tuple[ExternalAdapterKind, ...]
    missing_or_untrusted_adapters: tuple[ExternalAdapterKind, ...]

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-integration-readiness.v1",
            "capability": self.capability.value,
            "live_configured": self.live_configured,
            "required_adapters": [item.value for item in self.required_adapters],
            "missing_or_untrusted_adapters": [item.value for item in self.missing_or_untrusted_adapters],
            "fake_counts_as_connected": False,
            "security_certification": False,
            "deployment_approval": False,
        }


def evaluate_live_capability(
    *,
    probes: tuple[TrustedAdapterProbe, ...],
    capability: LiveCapability,
    now: datetime,
) -> IntegrationReadinessDecision:
    if not isinstance(probes, tuple) or not all(isinstance(item, TrustedAdapterProbe) for item in probes):
        raise ContractError("probes must be a tuple of TrustedAdapterProbe")
    if not isinstance(capability, LiveCapability):
        try:
            capability = LiveCapability(capability)
        except (TypeError, ValueError) as exc:
            raise ContractError("invalid live capability") from exc
    now = _aware(now, "now")
    by_kind: dict[ExternalAdapterKind, TrustedAdapterProbe] = {}
    for probe in probes:
        if probe.adapter_kind in by_kind:
            raise ContractError("duplicate adapter-kind probe")
        by_kind[probe.adapter_kind] = probe

    required = tuple(sorted(_REQUIRED_ADAPTERS[capability], key=lambda item: item.value))
    missing = tuple(
        item
        for item in required
        if item not in by_kind or not by_kind[item].connected_at(now)
    )
    return IntegrationReadinessDecision(
        capability=capability,
        live_configured=not missing,
        required_adapters=required,
        missing_or_untrusted_adapters=missing,
    )


FAKE_COUNTS_AS_CONNECTED = False
SECURITY_CERTIFICATION_FROM_READINESS = False
DEPLOYMENT_APPROVAL_FROM_READINESS = False
REAL_CONNECTOR_PROBES_CONFIGURED = False
