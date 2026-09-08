"""B53 integration health projection.

Customer-facing safe diagnostics for install/config/context/host-adapter/
local EnginePort fake availability.  Never exposes secrets, internal
bindings, raw exception traces, provider/model credentials, or canonical
CP state.  Distinguishes local conformance from Production readiness.
"""

from __future__ import annotations

from dataclasses import dataclass

from padiem_embedded_runtime.errors import SidecarContractError

STATUS_HEALTHY = "healthy"
STATUS_DEGRADED = "degraded"
STATUS_UNAVAILABLE = "unavailable"
HEALTH_STATUSES = frozenset({STATUS_HEALTHY, STATUS_DEGRADED, STATUS_UNAVAILABLE})

REASON_ALL_OK = "ALL_OK"
REASON_BOOTSTRAP_MISSING = "BOOTSTRAP_MISSING"
REASON_REGISTRATION_INCOMPLETE = "REGISTRATION_INCOMPLETE"
REASON_ONBOARDING_NOT_READY = "ONBOARDING_NOT_READY"
REASON_FAKE_ENGINE_PORT_ONLY = "FAKE_ENGINE_PORT_ONLY"
REASON_LOCAL_CONFORMANCE_ONLY = "LOCAL_CONFORMANCE_ONLY"
HEALTH_REASONS = frozenset({
    REASON_ALL_OK,
    REASON_BOOTSTRAP_MISSING,
    REASON_REGISTRATION_INCOMPLETE,
    REASON_ONBOARDING_NOT_READY,
    REASON_FAKE_ENGINE_PORT_ONLY,
    REASON_LOCAL_CONFORMANCE_ONLY,
})


@dataclass(frozen=True)
class IntegrationHealth:
    """Immutable public-safe integration health snapshot."""

    site_name: str
    status: str
    reason_code: str
    local_conformance: bool
    fake_engine_port_available: bool
    bootstrap_version: str
    adapter_id: str
    environment: str

    def __post_init__(self) -> None:
        if not isinstance(self.site_name, str) or not self.site_name:
            raise SidecarContractError("site_name must be non-empty text")
        if self.status not in HEALTH_STATUSES:
            raise SidecarContractError("status is not an allowlisted code")
        if self.reason_code not in HEALTH_REASONS:
            raise SidecarContractError("reason_code is not an allowlisted code")
        if not isinstance(self.local_conformance, bool):
            raise SidecarContractError("local_conformance must be a bool")
        if not isinstance(self.fake_engine_port_available, bool):
            raise SidecarContractError("fake_engine_port_available must be a bool")
        if not isinstance(self.bootstrap_version, str) or not self.bootstrap_version:
            raise SidecarContractError("bootstrap_version must be non-empty text")
        if not isinstance(self.adapter_id, str) or not self.adapter_id:
            raise SidecarContractError("adapter_id must be non-empty text")
        if self.environment not in ("dev", "preview", "production"):
            raise SidecarContractError("environment must be dev, preview, or production")

    def to_public_dict(self) -> dict[str, object]:
        return {
            "site_name": self.site_name,
            "status": self.status,
            "reason_code": self.reason_code,
            "local_conformance": self.local_conformance,
            "fake_engine_port_available": self.fake_engine_port_available,
            "bootstrap_version": self.bootstrap_version,
            "adapter_id": self.adapter_id,
            "environment": self.environment,
        }


def build_integration_health(
    site_name: str,
    bootstrap_version: str,
    adapter_id: str,
    environment: str,
    *,
    local_conformance: bool = True,
    fake_engine_port_available: bool = True,
    reason_code: str = REASON_ALL_OK,
) -> IntegrationHealth:
    """Build an integration health snapshot from validated inputs."""
    if reason_code not in HEALTH_REASONS:
        raise SidecarContractError("reason_code is not an allowlisted code")
    status = STATUS_HEALTHY if reason_code == REASON_ALL_OK else STATUS_DEGRADED
    return IntegrationHealth(
        site_name=site_name,
        status=status,
        reason_code=reason_code,
        local_conformance=local_conformance,
        fake_engine_port_available=fake_engine_port_available,
        bootstrap_version=bootstrap_version,
        adapter_id=adapter_id,
        environment=environment,
    )