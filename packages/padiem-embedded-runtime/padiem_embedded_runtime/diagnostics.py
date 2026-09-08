"""Public-safe integration diagnostics for IP-SIDECAR (S3).

Diagnostics report only bounded status/reason codes. They never carry raw
exceptions, stack traces, credentials, provider material, or Engine content:
unclassified input fails closed at construction, and the projected view is
built exclusively from allowlisted enum values.
"""

from __future__ import annotations

from dataclasses import dataclass

from .compatibility import VersionCompatibility
from .errors import SidecarContractError

STATUS_READY = "ready"
STATUS_DEGRADED = "degraded"
STATUS_DISABLED = "disabled"
DIAGNOSTIC_STATUSES = frozenset({STATUS_READY, STATUS_DEGRADED, STATUS_DISABLED})

REASON_OK = "OK"
REASON_VERSION_INCOMPATIBLE = "VERSION_INCOMPATIBLE"
REASON_CONTEXT_MALFORMED = "CONTEXT_MALFORMED"
REASON_BOOTSTRAP_REJECTED = "BOOTSTRAP_REJECTED"
REASON_SHELL_DISABLED = "SHELL_DISABLED"
DIAGNOSTIC_REASONS = frozenset(
    {
        REASON_OK,
        REASON_VERSION_INCOMPATIBLE,
        REASON_CONTEXT_MALFORMED,
        REASON_BOOTSTRAP_REJECTED,
        REASON_SHELL_DISABLED,
    }
)


@dataclass(frozen=True)
class IntegrationDiagnostics:
    """Immutable public-safe diagnostic snapshot for one host integration."""

    host_id: str
    status: str
    reason_code: str
    contract_supported: bool
    dropped_reserved_count: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.host_id, str) or not self.host_id:
            raise SidecarContractError("diagnostics host_id must be non-empty text")
        if self.status not in DIAGNOSTIC_STATUSES:
            raise SidecarContractError("diagnostics status is not an allowlisted code")
        if self.reason_code not in DIAGNOSTIC_REASONS:
            raise SidecarContractError("diagnostics reason_code is not an allowlisted code")
        if not isinstance(self.contract_supported, bool):
            raise SidecarContractError("diagnostics contract_supported must be a bool")
        if not isinstance(self.dropped_reserved_count, int) or isinstance(
            self.dropped_reserved_count, bool
        ):
            raise SidecarContractError("diagnostics dropped_reserved_count must be an int")
        if self.dropped_reserved_count < 0:
            raise SidecarContractError("diagnostics dropped_reserved_count must be >= 0")

    def to_public_dict(self) -> dict[str, object]:
        return {
            "host_id": self.host_id,
            "status": self.status,
            "reason_code": self.reason_code,
            "contract_supported": self.contract_supported,
            "dropped_reserved_count": self.dropped_reserved_count,
        }


_REASON_STATUS = {
    REASON_OK: STATUS_READY,
    REASON_VERSION_INCOMPATIBLE: STATUS_DISABLED,
    REASON_BOOTSTRAP_REJECTED: STATUS_DISABLED,
    REASON_SHELL_DISABLED: STATUS_DISABLED,
    REASON_CONTEXT_MALFORMED: STATUS_DEGRADED,
}


def build_diagnostics(
    host_id: str,
    compatibility: VersionCompatibility,
    reason_code: str = REASON_OK,
    *,
    dropped_reserved_count: int = 0,
) -> IntegrationDiagnostics:
    """Derive a diagnostic snapshot from an already-validated verdict + reason.

    Status is a pure function of the allowlisted reason code, so the public
    surface can never drift from the reason it reports.
    """
    if not isinstance(compatibility, VersionCompatibility):
        raise SidecarContractError("diagnostics require a VersionCompatibility verdict")
    if reason_code not in DIAGNOSTIC_REASONS:
        raise SidecarContractError("diagnostics reason_code is not an allowlisted code")
    return IntegrationDiagnostics(
        host_id=host_id,
        status=_REASON_STATUS[reason_code],
        reason_code=reason_code,
        contract_supported=compatibility.supported,
        dropped_reserved_count=dropped_reserved_count,
    )
