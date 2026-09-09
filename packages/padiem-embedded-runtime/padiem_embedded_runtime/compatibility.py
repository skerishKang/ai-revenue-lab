"""Deterministic runtime/host contract version compatibility for IP-SIDECAR (S3).

Host-reported contract versions are untrusted input. This module never raises
for malformed values: it returns a bounded, public-safe
:class:`VersionCompatibility` result so callers can fail over to a
host-safe degraded/disabled path instead of breaking the host journey.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

RUNTIME_CONTRACT_MAJOR = 1
RUNTIME_CONTRACT_MINOR = 0
RUNTIME_CONTRACT_VERSION = f"{RUNTIME_CONTRACT_MAJOR}.{RUNTIME_CONTRACT_MINOR}"

SUPPORTED_CONTRACT_MAJORS = frozenset({RUNTIME_CONTRACT_MAJOR})

REASON_COMPATIBLE = "COMPATIBLE"
REASON_UNSUPPORTED_MAJOR = "UNSUPPORTED_CONTRACT_MAJOR"
REASON_MALFORMED_VERSION = "MALFORMED_CONTRACT_VERSION"
REASON_MISSING_VERSION = "MISSING_CONTRACT_VERSION"

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)$")


@dataclass(frozen=True)
class VersionCompatibility:
    """Public-safe, deterministic compatibility verdict. Never carries raw input."""

    supported: bool
    reason_code: str
    host_version: str
    runtime_version: str = RUNTIME_CONTRACT_VERSION

    def to_public_dict(self) -> dict[str, object]:
        return {
            "supported": self.supported,
            "reason_code": self.reason_code,
            "host_version": self.host_version,
            "runtime_version": self.runtime_version,
        }


def _bounded_repr(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value[:32]


def check_contract_compatibility(raw_version: object) -> VersionCompatibility:
    """Classify one host-reported contract version against the runtime contract.

    Only MAJOR.MINOR digit versions are accepted; the runtime supports the
    current major only. Malformed or missing values yield an unsupported
    result with a stable reason code instead of raising.
    """
    if raw_version is None:
        return VersionCompatibility(
            supported=False,
            reason_code=REASON_MISSING_VERSION,
            host_version="",
        )
    if not isinstance(raw_version, str) or _VERSION_RE.fullmatch(raw_version) is None:
        return VersionCompatibility(
            supported=False,
            reason_code=REASON_MALFORMED_VERSION,
            host_version=_bounded_repr(raw_version),
        )
    major = int(raw_version.split(".", 1)[0])
    if major not in SUPPORTED_CONTRACT_MAJORS:
        return VersionCompatibility(
            supported=False,
            reason_code=REASON_UNSUPPORTED_MAJOR,
            host_version=raw_version,
        )
    return VersionCompatibility(
        supported=True,
        reason_code=REASON_COMPATIBLE,
        host_version=raw_version,
    )
