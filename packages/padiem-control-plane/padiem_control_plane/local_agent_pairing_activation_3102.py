"""#3102 — live pairing activation readiness and rollback contract.

This module contains **no** activation logic. It is the source-level contract
that records what a live deployment must satisfy, what is still unbound, and how
to turn the path back off. It deliberately creates no new pairing, device,
session or credential authority:

    SECOND_PAIRING_AUTHORITY=0
    SECOND_DEVICE_LIFECYCLE_AUTHORITY=0
    SECOND_SESSION_AUTHORITY=0
    SECOND_CREDENTIAL_STORE=0
    SECOND_TLS_AUTHORITY=0
    GENERIC_RATE_AUTHORITY=0

Everything it describes is delegated to the canonical #3080 surfaces:

* challenge issuance / single-use / expiry — `InMemoryBrokerPairingAuthority`
  and its HTTP routes;
* device lifecycle (unpaired, paired_offline, online, revoked,
  credential_expired, update_required) — `kagent.local_agent_pairing`;
* server-backed ONLINE — `kagent.local_agent_server_projection`;
* credential custody — `DeviceCredentialStore` via the pinned transport.

The posture recorded here is source-only:

    SOURCE_READY=YES
    PRODUCTION_ACTIVATION=NO
    LIVE_PRODUCTION_PAIRING_CALL=0

No secret value, endpoint value, or credential is created, stored or printed by
this module. Names of the bindings that an activation would need are recorded as
*names only*.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .contracts import ControlPlaneContractError

#: Binding names an activation would have to supply. Names only — this module
#: never reads, writes, returns or logs a value for any of them.
REQUIRED_ACTIVATION_BINDING_NAMES: tuple[str, ...] = (
    "PAIREM_BROKER_PAIRING_PEPPER",
    "PAIREM_BROKER_HMAC_PEPPER",
    "PAIREM_BROKER_TRUSTED_ORIGIN",
    "PAIREM_BROKER_TLS_CERT_REF",
    "PAIREM_PAIRING_ISSUANCE_RATE_LIMIT",
)

#: Rollback is a disable, never a delete. Durable pairing state and issued
#: credentials are left intact so a later activation does not strand devices.
ROLLBACK_DISABLED_BY_DEFAULT = True


@dataclass(frozen=True, slots=True)
class PairingActivationReadiness:
    """Secret-free readiness record for one live pairing deployment.

    Every field is a boolean or an enumerated posture. No secret, endpoint value,
    challenge code or credential can appear here.
    """

    source_ready: bool
    production_activated: bool
    trusted_tls_required: bool
    outbound_only_desktop: bool
    public_inbound_port: bool
    upnp_required: bool
    caller_endpoint_override: bool
    challenge_ttl_bounded: bool
    challenge_single_use: bool
    issuance_rate_bound_active: bool
    revoke_path_available: bool
    rotate_path_available: bool
    server_backed_online_only: bool
    canonical_authorities_reused: bool

    def __post_init__(self) -> None:
        for field_name in self.__slots__:
            value = getattr(self, field_name)
            if not isinstance(value, bool):
                raise ControlPlaneContractError(f"{field_name} must be a boolean")

    def missing_prerequisites(self) -> tuple[str, ...]:
        """Names of the activation prerequisites that are not yet satisfied."""
        gaps: list[str] = []
        if not self.trusted_tls_required:
            gaps.append("trusted_tls_required")
        if self.public_inbound_port:
            gaps.append("public_inbound_port_must_be_zero")
        if self.upnp_required:
            gaps.append("upnp_required_must_be_false")
        if self.caller_endpoint_override:
            gaps.append("caller_endpoint_override_must_be_false")
        if not self.challenge_ttl_bounded:
            gaps.append("challenge_ttl_bounded")
        if not self.challenge_single_use:
            gaps.append("challenge_single_use")
        if not self.issuance_rate_bound_active:
            gaps.append("issuance_rate_bound_active")
        if not self.revoke_path_available:
            gaps.append("revoke_path_available")
        if not self.rotate_path_available:
            gaps.append("rotate_path_available")
        if not self.server_backed_online_only:
            gaps.append("server_backed_online_only")
        if not self.canonical_authorities_reused:
            gaps.append("canonical_authorities_reused")
        return tuple(gaps)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-live-pairing-activation-readiness.v1",
            "source_ready": self.source_ready,
            "production_activated": self.production_activated,
            "trusted_tls_required": self.trusted_tls_required,
            "outbound_only_desktop": self.outbound_only_desktop,
            "public_inbound_port": self.public_inbound_port,
            "upnp_required": self.upnp_required,
            "caller_endpoint_override": self.caller_endpoint_override,
            "challenge_ttl_bounded": self.challenge_ttl_bounded,
            "challenge_single_use": self.challenge_single_use,
            "issuance_rate_bound_active": self.issuance_rate_bound_active,
            "revoke_path_available": self.revoke_path_available,
            "rotate_path_available": self.rotate_path_available,
            "server_backed_online_only": self.server_backed_online_only,
            "canonical_authorities_reused": self.canonical_authorities_reused,
            "activation_blockers": list(self.missing_prerequisites()),
            "required_binding_names": list(REQUIRED_ACTIVATION_BINDING_NAMES),
            "binding_values_present": False,
            "rollback_disable_path": "disable_binding_only_no_state_deletion",
            "secret_material_exposed": False,
        }


#: The source-only posture this branch actually ships. Production activation is
#: a separate CENTRAL decision, so `production_activated` is False and the
#: issuance rate bound is not yet bound.
SOURCE_ONLY_READINESS = PairingActivationReadiness(
    source_ready=True,
    production_activated=False,
    trusted_tls_required=True,
    outbound_only_desktop=True,
    public_inbound_port=False,
    upnp_required=False,
    caller_endpoint_override=False,
    challenge_ttl_bounded=True,
    challenge_single_use=True,
    issuance_rate_bound_active=False,
    revoke_path_available=True,
    rotate_path_available=True,
    server_backed_online_only=True,
    canonical_authorities_reused=True,
)


def assert_not_activated(readiness: PairingActivationReadiness = SOURCE_ONLY_READINESS) -> None:
    """Fail closed if anything claims a live pairing activation happened.

    The branch under review is source-only. If a future change flips
    `production_activated`, this guard is the place a reviewer will notice.
    """
    if readiness.production_activated:
        raise ControlPlaneContractError(
            "pairing_activation_not_permitted_on_this_branch",
            "live pairing activation requires a separate CENTRAL decision",
        )


#: Ordered activation runbook. Executing it is out of scope for this branch; it
#: exists so the sequence is reviewed before anyone runs it.
ACTIVATION_RUNBOOK: tuple[str, ...] = (
    "preflight: confirm this branch's exact head is the reviewed commit",
    "verify: canonical authorities are reused and SECOND_*_AUTHORITY are all 0",
    "verify: no public inbound port, no UPnP, outbound-only Desktop path",
    "bind: trusted TLS origin and certificate reference for the fixed broker destination",
    "bind: deployment peppers required by the canonical pairing authority (names only here)",
    "bind: a positive per-scope issuance rate limit on the canonical authority",
    "enable: flip the activation flag for one account/workspace canary only",
    "canary: issue one challenge, redeem it once, confirm the binding is PAIRED_OFFLINE",
    "canary: confirm ONLINE appears only after a canonical session plus server heartbeat",
    "test: revoke the canary binding and confirm the credential stops working",
    "test: rotate/expire the canary credential and confirm repair via the canonical flow",
    "verify: logs and support projections contain no secret material",
    "rollback: disable the activation flag; leave durable state and credentials intact",
)

ROLLBACK_RUNBOOK: tuple[str, ...] = (
    "disable: turn the activation flag off so challenge issuance refuses new scopes",
    "verify: issuance refuses closed and existing ONLINE projections are not forged",
    "revoke: revoke outstanding canary bindings through the canonical revoke path",
    "preserve: keep durable pairing state and credential digests; never delete them",
    "verify: no secret value appears in logs, diagnostics or support evidence",
    "record: note the disabled posture and the exact head in the audit report",
)

SECRET_FREE_DIAGNOSTIC_KEYS: frozenset[str] = frozenset(
    {
        "contract_version",
        "source_ready",
        "production_activated",
        "activation_blockers",
        "required_binding_names",
        "challenge_ttl_bounded",
        "challenge_single_use",
        "issuance_rate_bound_active",
        "revoke_path_available",
        "rotate_path_available",
        "server_backed_online_only",
        "trusted_tls_required",
        "caller_endpoint_override",
        "canonical_authorities_reused",
        "public_inbound_port",
        "upnp_required",
        "outbound_only_desktop",
        "rollback_disable_path",
        "secret_material_exposed",
        "binding_values_present",
    }
)


def assert_secret_free(projection: dict[str, Any]) -> None:
    """Reject a support projection that carries anything outside the safe key set.

    This is a structural check on key names, not a value scan: it guarantees the
    diagnostic surface cannot grow a secret-bearing field in the first place.
    """
    if not isinstance(projection, dict):
        raise ControlPlaneContractError("pairing projection must be a mapping")
    extra = set(projection) - SECRET_FREE_DIAGNOSTIC_KEYS
    if extra:
        raise ControlPlaneContractError(
            "pairing_projection_not_secret_free",
            f"support projection carries unexpected fields: {sorted(extra)}",
        )


__all__ = [
    "ACTIVATION_RUNBOOK",
    "REQUIRED_ACTIVATION_BINDING_NAMES",
    "ROLLBACK_RUNBOOK",
    "SECRET_FREE_DIAGNOSTIC_KEYS",
    "SOURCE_ONLY_READINESS",
    "PairingActivationReadiness",
    "assert_not_activated",
    "assert_secret_free",
]
