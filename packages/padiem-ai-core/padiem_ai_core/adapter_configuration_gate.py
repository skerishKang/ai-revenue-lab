"""External adapter configuration gate for live capabilities.

Determines whether a set of external adapter probes satisfies a named
live capability.  UNCONFIGURED and DETERMINISTIC_FAKE probes never
satisfy the gate.  CONNECTED probes must carry issued/expires timestamps
and authority-evidence references.  Stale (expired) and future (issued
in the future beyond a small clock-skew tolerance) probes fail closed.

This module contains no real connector calls, no security-certification
claim, and no deployment-approval logic.  It is a pure, stdlib-only,
network-free contract.

Required semantics (issue #1567):
    UNCONFIGURED_COUNTS_AS_CONNECTED = NO
    DETERMINISTIC_FAKE_COUNTS_AS_CONNECTED = NO
    CONNECTED_REQUIRES_ISSUED_EXPIRES = YES
    CONNECTED_REQUIRES_AUTHORITY_EVIDENCE_REFS = YES
    STALE_PROBE_FAILS_CLOSED = YES
    FUTURE_PROBE_FAILS_CLOSED = YES
    MISSING_ADAPTERS_VISIBLE = YES
    SECURITY_CERTIFICATION = NO
    DEPLOYMENT_APPROVAL = NO
    REAL_CONNECTOR_CALL = NO
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import re


_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,255}$")
MAX_CLOCK_SKEW_SECONDS = 30


class AdapterConfigurationGateError(ValueError):
    """Raised when an adapter configuration gate contract is violated."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.safe_message = message


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ExternalAdapterKind(str, Enum):
    """Known external adapter kinds for live-capability gating."""

    CONTROL_PLANE_IDENTITY = "control_plane_identity"
    CONTROL_PLANE_ENTITLEMENT = "control_plane_entitlement"
    B14_MODEL_EXECUTION = "b14_model_execution"
    SANDBOX_PROVIDER = "sandbox_provider"
    GITHUB_REPOSITORY_READ = "github_repository_read"
    GITHUB_DRAFT_WRITE = "github_draft_write"
    COMMUNICATION_OUTBOUND = "communication_outbound"
    ACCOUNTING_READ = "accounting_read"


class AdapterProbeState(str, Enum):
    """Connection state of an external adapter probe."""

    UNCONFIGURED = "unconfigured"
    DETERMINISTIC_FAKE = "deterministic_fake"
    CONNECTED = "connected"


class LiveCapability(str, Enum):
    """Named live capabilities whose gates are evaluated."""

    MANAGED_CLOUD_RUN = "managed_cloud_run"
    DRAFT_PR_OUTPUT = "draft_pr_output"
    BUSINESS_MESSAGING = "business_messaging"
    FINANCE_PROJECTION_LIVE_READ = "finance_projection_live_read"


# ---------------------------------------------------------------------------
# Capability requirements (server-defined, immutable)
# ---------------------------------------------------------------------------

_CAPABILITY_REQUIREMENTS: dict[LiveCapability, tuple[ExternalAdapterKind, ...]] = {
    LiveCapability.MANAGED_CLOUD_RUN: (
        ExternalAdapterKind.CONTROL_PLANE_IDENTITY,
        ExternalAdapterKind.CONTROL_PLANE_ENTITLEMENT,
        ExternalAdapterKind.B14_MODEL_EXECUTION,
        ExternalAdapterKind.SANDBOX_PROVIDER,
        ExternalAdapterKind.GITHUB_REPOSITORY_READ,
    ),
    LiveCapability.DRAFT_PR_OUTPUT: (
        ExternalAdapterKind.CONTROL_PLANE_IDENTITY,
        ExternalAdapterKind.CONTROL_PLANE_ENTITLEMENT,
        ExternalAdapterKind.B14_MODEL_EXECUTION,
        ExternalAdapterKind.SANDBOX_PROVIDER,
        ExternalAdapterKind.GITHUB_REPOSITORY_READ,
        ExternalAdapterKind.GITHUB_DRAFT_WRITE,
    ),
    LiveCapability.BUSINESS_MESSAGING: (
        ExternalAdapterKind.CONTROL_PLANE_IDENTITY,
        ExternalAdapterKind.CONTROL_PLANE_ENTITLEMENT,
        ExternalAdapterKind.COMMUNICATION_OUTBOUND,
    ),
    LiveCapability.FINANCE_PROJECTION_LIVE_READ: (
        ExternalAdapterKind.CONTROL_PLANE_IDENTITY,
        ExternalAdapterKind.CONTROL_PLANE_ENTITLEMENT,
        ExternalAdapterKind.ACCOUNTING_READ,
    ),
}


# ---------------------------------------------------------------------------
# Probe data
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AdapterProbe:
    """A trusted bounded probe projection for one external adapter.

    ``state`` must be a server-trusted probe result.  CONNECTED probes
    require ``issued_at`` / ``expires_at`` timestamps and at least one
    authority-evidence reference.
    """

    adapter_kind: ExternalAdapterKind
    state: AdapterProbeState
    issued_at: datetime | None = None
    expires_at: datetime | None = None
    authority_evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.adapter_kind, ExternalAdapterKind):
            raise AdapterConfigurationGateError(
                "adapter_kind", "must be an ExternalAdapterKind member"
            )
        if not isinstance(self.state, AdapterProbeState):
            raise AdapterConfigurationGateError(
                "state", "must be an AdapterProbeState member"
            )
        if self.state is AdapterProbeState.CONNECTED:
            if self.issued_at is None or self.expires_at is None:
                raise AdapterConfigurationGateError(
                    "probe",
                    "CONNECTED probe requires issued_at and expires_at",
                )
            if self.issued_at.tzinfo is None or self.expires_at.tzinfo is None:
                raise AdapterConfigurationGateError(
                    "probe",
                    "CONNECTED probe timestamps must be timezone-aware",
                )
            if not self.authority_evidence_refs:
                raise AdapterConfigurationGateError(
                    "probe",
                    "CONNECTED probe requires at least one authority_evidence_ref",
                )
            for ref in self.authority_evidence_refs:
                if not isinstance(ref, str) or not _SAFE_ID_RE.fullmatch(ref):
                    raise AdapterConfigurationGateError(
                        "authority_evidence_ref",
                        f"'{ref}' is not a safe identifier",
                    )


# ---------------------------------------------------------------------------
# Gate result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CapabilityGateResult:
    """Outcome of evaluating a live capability gate."""

    capability: LiveCapability
    satisfied: bool
    required_adapters: tuple[ExternalAdapterKind, ...]
    connected_adapters: tuple[ExternalAdapterKind, ...]
    missing_adapters: tuple[ExternalAdapterKind, ...]
    stale_probes: tuple[ExternalAdapterKind, ...]
    future_probes: tuple[ExternalAdapterKind, ...]
    unconfigured_adapters: tuple[ExternalAdapterKind, ...]
    fake_adapters: tuple[ExternalAdapterKind, ...]


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------


def evaluate_capability_gate(
    capability: LiveCapability,
    probes: tuple[AdapterProbe, ...],
    *,
    now: datetime | None = None,
) -> CapabilityGateResult:
    """Evaluate whether ``probes`` satisfy a named live capability.

    Fails safe: UNCONFIGURED, DETERMINISTIC_FAKE, stale, and future
    probes are never counted as connected.  The result always includes
    the full inventory of missing/stale/future/unconfigured/fake
    adapters so callers can surface them.
    """
    if not isinstance(capability, LiveCapability):
        raise AdapterConfigurationGateError(
            "capability", "must be a LiveCapability member"
        )

    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        raise AdapterConfigurationGateError("now", "must be timezone-aware")

    required = _CAPABILITY_REQUIREMENTS[capability]

    probe_by_kind: dict[ExternalAdapterKind, AdapterProbe] = {}
    for probe in probes:
        if not isinstance(probe, AdapterProbe):
            raise AdapterConfigurationGateError("probe", "every probe must be an AdapterProbe")
        probe_by_kind[probe.adapter_kind] = probe

    connected: list[ExternalAdapterKind] = []
    missing: list[ExternalAdapterKind] = []
    stale: list[ExternalAdapterKind] = []
    future: list[ExternalAdapterKind] = []
    unconfigured: list[ExternalAdapterKind] = []
    fake: list[ExternalAdapterKind] = []

    for kind in required:
        probe = probe_by_kind.get(kind)
        if probe is None:
            missing.append(kind)
            continue

        if probe.state is AdapterProbeState.UNCONFIGURED:
            unconfigured.append(kind)
            continue

        if probe.state is AdapterProbeState.DETERMINISTIC_FAKE:
            fake.append(kind)
            continue

        # CONNECTED — check temporal validity
        assert probe.issued_at is not None
        assert probe.expires_at is not None

        if probe.expires_at < now:
            stale.append(kind)
            continue

        if probe.issued_at > now + timedelta(seconds=MAX_CLOCK_SKEW_SECONDS):
            future.append(kind)
            continue

        connected.append(kind)

    satisfied = len(connected) == len(required)

    return CapabilityGateResult(
        capability=capability,
        satisfied=satisfied,
        required_adapters=required,
        connected_adapters=tuple(connected),
        missing_adapters=tuple(missing),
        stale_probes=tuple(stale),
        future_probes=tuple(future),
        unconfigured_adapters=tuple(unconfigured),
        fake_adapters=tuple(fake),
    )


def required_adapters_for(capability: LiveCapability) -> tuple[ExternalAdapterKind, ...]:
    """Return the required adapter set for a capability (read-only)."""
    if not isinstance(capability, LiveCapability):
        raise AdapterConfigurationGateError(
            "capability", "must be a LiveCapability member"
        )
    return _CAPABILITY_REQUIREMENTS[capability]
