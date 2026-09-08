"""Host-context bridge for IP-SIDECAR (S3).

Composes the S3 pipeline over one untrusted host payload:

    untrusted host page/app context
      -> bounded normalization (host_context / bootstrap contracts)
      -> explicit allowlisted fields only
      -> public-safe bootstrap/session projection
      -> runtime contract version compatibility
      -> host-safe degraded/disabled result on invalid/incompatible input

The bridge never raises for untrusted data: every failure path returns a
:class:`BridgeOutcome` carrying only public-safe status/reason codes, so the
host primary journey keeps working. Client-supplied tenant/user/role/
entitlement fields stay untrusted; nothing here promotes them to authority.

Fail-safe policy:
- rejected bootstrap      -> shell disabled (nothing safe to mount);
- incompatible contract   -> shell disabled (host must not rely on the panel);
- malformed context       -> degraded (identity stays usable, context dropped);
- valid input             -> ready.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional

from .bootstrap import BootstrapConfig, parse_bootstrap_config
from .compatibility import VersionCompatibility, check_contract_compatibility
from .diagnostics import (
    REASON_BOOTSTRAP_REJECTED,
    REASON_CONTEXT_MALFORMED,
    REASON_OK,
    REASON_SHELL_DISABLED,
    REASON_VERSION_INCOMPATIBLE,
    STATUS_READY,
    IntegrationDiagnostics,
    build_diagnostics,
)
from .errors import SidecarContractError
from .host_context import HostContextEnvelope, envelop_host_context
from .lifecycle import DISABLED, EmbeddedShell

BRIDGE_CONTRACT_FIELD = "contract_version"


@dataclass(frozen=True)
class SessionProjection:
    """Public-safe bootstrap/session view: identifiers and capabilities only."""

    host_id: str
    shell_version: str
    locale: str
    features: tuple[str, ...]
    trust_level: str
    context_fields: tuple[tuple[str, str], ...]
    dropped_reserved: tuple[str, ...]

    def to_public_dict(self) -> dict[str, object]:
        return {
            "host_id": self.host_id,
            "shell_version": self.shell_version,
            "locale": self.locale,
            "features": list(self.features),
            "trust_level": self.trust_level,
            "context_fields": {key: value for key, value in self.context_fields},
            "dropped_reserved": list(self.dropped_reserved),
        }


@dataclass(frozen=True)
class BridgeOutcome:
    """Host-safe result of one bridge intake; safe to return to any host."""

    accepted: bool
    status: str
    projection: Optional[SessionProjection]
    compatibility: VersionCompatibility
    diagnostics: IntegrationDiagnostics

    def to_public_dict(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "status": self.status,
            "projection": self.projection.to_public_dict() if self.projection else None,
            "compatibility": self.compatibility.to_public_dict(),
            "diagnostics": self.diagnostics.to_public_dict(),
        }


def _rejected(
    host_id: str,
    compatibility: VersionCompatibility,
    reason_code: str,
    shell: EmbeddedShell,
) -> BridgeOutcome:
    if shell.state != DISABLED:
        shell.disable(reason_code)
    diagnostics = build_diagnostics(host_id, compatibility, reason_code)
    return BridgeOutcome(
        accepted=False,
        status=diagnostics.status,
        projection=None,
        compatibility=compatibility,
        diagnostics=diagnostics,
    )


def intake_host_payload(
    raw_bootstrap: Mapping[str, object],
    raw_context: Mapping[str, object],
    shell: EmbeddedShell,
) -> BridgeOutcome:
    """Run the full untrusted-context pipeline and return a host-safe outcome.

    ``raw_bootstrap`` carries the host-reported ``contract_version`` alongside
    bootstrap fields; the bridge consumes that field for the compatibility
    check and strips it before the bootstrap contract parse, so unknown-field
    rejection still applies to everything else. On invalid or incompatible
    input the shell is disabled fail-safe and the outcome carries only
    public-safe status/reason codes.
    """
    if not isinstance(shell, EmbeddedShell):
        raise SidecarContractError("bridge requires a validated EmbeddedShell")
    if not isinstance(raw_bootstrap, Mapping):
        raw_bootstrap = {}

    contract_version: object = raw_bootstrap.get(BRIDGE_CONTRACT_FIELD)
    bootstrap_raw = {
        key: value for key, value in raw_bootstrap.items() if key != BRIDGE_CONTRACT_FIELD
    }
    compatibility = check_contract_compatibility(contract_version)

    if shell.state == DISABLED:
        diagnostics = build_diagnostics(
            shell.host_id, compatibility, REASON_SHELL_DISABLED
        )
        return BridgeOutcome(
            accepted=False,
            status=diagnostics.status,
            projection=None,
            compatibility=compatibility,
            diagnostics=diagnostics,
        )

    host_id_guess = bootstrap_raw.get("host_id")
    host_id = host_id_guess if isinstance(host_id_guess, str) and host_id_guess else "unknown-host"

    try:
        config: BootstrapConfig = parse_bootstrap_config(bootstrap_raw)
    except SidecarContractError:
        return _rejected(host_id, compatibility, REASON_BOOTSTRAP_REJECTED, shell)

    if not compatibility.supported:
        return _rejected(
            config.host_id, compatibility, REASON_VERSION_INCOMPATIBLE, shell
        )

    try:
        envelope: HostContextEnvelope = envelop_host_context(config.host_id, raw_context)
    except SidecarContractError:
        diagnostics = build_diagnostics(
            config.host_id, compatibility, REASON_CONTEXT_MALFORMED
        )
        return BridgeOutcome(
            accepted=False,
            status=diagnostics.status,
            projection=None,
            compatibility=compatibility,
            diagnostics=diagnostics,
        )

    projection = SessionProjection(
        host_id=config.host_id,
        shell_version=config.shell_version,
        locale=config.locale,
        features=config.features,
        trust_level=envelope.trust_level,
        context_fields=envelope.fields,
        dropped_reserved=envelope.dropped_reserved,
    )
    diagnostics = build_diagnostics(
        config.host_id,
        compatibility,
        REASON_OK,
        dropped_reserved_count=len(envelope.dropped_reserved),
    )
    return BridgeOutcome(
        accepted=diagnostics.status == STATUS_READY,
        status=diagnostics.status,
        projection=projection,
        compatibility=compatibility,
        diagnostics=diagnostics,
    )
