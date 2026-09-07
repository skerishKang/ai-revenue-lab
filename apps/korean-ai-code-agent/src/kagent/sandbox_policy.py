"""Explicit sandbox policy and provider-neutral contracts for Cloud M1 (#1405).

Provides canonical value objects and acceptance gates matching threat-model requirements:
- SandboxNetworkPolicy
- SandboxResourceLimits
- SandboxFilesystemPolicy
- SandboxArtifactPolicy
- SandboxLeaseSecurityPolicy
- SandboxProviderAcceptanceGate
- VerifiedDiffEvidenceContract
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any

from .contracts import ContractError, ExecutionMode, NetworkPolicy, ResourceClass, SandboxLeaseRequest
from .sandbox_conformance import (
    IsolationPrimitive,
    SandboxArtifactManifest,
    SandboxArtifactRef,
    SandboxProviderAssessment,
    SandboxProviderCapabilities,
    SandboxProviderConformanceGate,
    SandboxSecurityPolicy,
    VerifiedDiffEvidence,
    REAL_SANDBOX_PROVIDER_SELECTED,
    REAL_SANDBOX_PROVIDER_CALLS,
    PRODUCTION_SANDBOX_CLAIM,
)
from .security import redact_secrets

_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class SandboxNetworkPolicy(str, Enum):
    OFF = "off"
    RESTRICTED = "restricted"

    @property
    def is_deny_by_default(self) -> bool:
        return self is SandboxNetworkPolicy.OFF


@dataclass(frozen=True, slots=True)
class SandboxResourceLimits:
    max_cpu_cores: int = 4
    max_memory_mb: int = 8192
    max_disk_mb: int = 10240
    max_process_count: int = 256
    max_ttl_seconds: int = 3600

    def __post_init__(self) -> None:
        if isinstance(self.max_cpu_cores, bool) or not isinstance(self.max_cpu_cores, int) or not 1 <= self.max_cpu_cores <= 64:
            raise ContractError("max_cpu_cores must be between 1 and 64")
        if isinstance(self.max_memory_mb, bool) or not isinstance(self.max_memory_mb, int) or not 256 <= self.max_memory_mb <= 65536:
            raise ContractError("max_memory_mb must be between 256 and 65536")
        if isinstance(self.max_disk_mb, bool) or not isinstance(self.max_disk_mb, int) or not 512 <= self.max_disk_mb <= 102400:
            raise ContractError("max_disk_mb must be between 512 and 102400")
        if isinstance(self.max_process_count, bool) or not isinstance(self.max_process_count, int) or not 16 <= self.max_process_count <= 2048:
            raise ContractError("max_process_count must be between 16 and 2048")
        if isinstance(self.max_ttl_seconds, bool) or not isinstance(self.max_ttl_seconds, int) or not 60 <= self.max_ttl_seconds <= 3600:
            raise ContractError("max_ttl_seconds must be between 60 and 3600")


@dataclass(frozen=True, slots=True)
class SandboxFilesystemPolicy:
    host_mounts_allowed: bool = False
    runtime_socket_exposed: bool = False
    workspace_reuse_allowed: bool = False
    checkout_hooks_disabled: bool = True
    writable_workspace: bool = True

    def __post_init__(self) -> None:
        if self.host_mounts_allowed is not False:
            raise ContractError("Cloud M1 host_mounts_allowed must be false")
        if self.runtime_socket_exposed is not False:
            raise ContractError("Cloud M1 runtime_socket_exposed must be false")
        if self.workspace_reuse_allowed is not False:
            raise ContractError("Cloud M1 workspace_reuse_allowed must be false")
        if self.checkout_hooks_disabled is not True:
            raise ContractError("Cloud M1 checkout_hooks_disabled must be true")
        if not isinstance(self.writable_workspace, bool):
            raise ContractError("writable_workspace must be boolean")


@dataclass(frozen=True, slots=True)
class SandboxArtifactPolicy:
    max_artifact_bytes: int = 25 * 1024 * 1024
    max_artifact_count: int = 100
    max_terminal_output_bytes: int = 2 * 1024 * 1024
    terminal_output_sanitized: bool = True
    allowed_artifact_kinds: tuple[str, ...] = ("diff", "test_report", "junit_xml", "log")

    def __post_init__(self) -> None:
        if isinstance(self.max_artifact_bytes, bool) or not isinstance(self.max_artifact_bytes, int) or not 1024 <= self.max_artifact_bytes <= 100 * 1024 * 1024:
            raise ContractError("max_artifact_bytes must be between 1024 and 104857600")
        if isinstance(self.max_artifact_count, bool) or not isinstance(self.max_artifact_count, int) or not 1 <= self.max_artifact_count <= 1000:
            raise ContractError("max_artifact_count must be between 1 and 1000")
        if isinstance(self.max_terminal_output_bytes, bool) or not isinstance(self.max_terminal_output_bytes, int) or not 1024 <= self.max_terminal_output_bytes <= 20 * 1024 * 1024:
            raise ContractError("max_terminal_output_bytes must be between 1024 and 20971520")
        if self.terminal_output_sanitized is not True:
            raise ContractError("Cloud M1 terminal_output_sanitized must be true")
        if not isinstance(self.allowed_artifact_kinds, tuple) or not self.allowed_artifact_kinds:
            raise ContractError("allowed_artifact_kinds must be a non-empty tuple of strings")


@dataclass(frozen=True, slots=True)
class SandboxLeaseSecurityPolicy:
    network_policy: SandboxNetworkPolicy = SandboxNetworkPolicy.OFF
    privileged_runtime_allowed: bool = False
    host_secret_inheritance_allowed: bool = False
    provider_metadata_access_allowed: bool = False
    resource_limits: SandboxResourceLimits = field(default_factory=SandboxResourceLimits)
    filesystem_policy: SandboxFilesystemPolicy = field(default_factory=SandboxFilesystemPolicy)
    artifact_policy: SandboxArtifactPolicy = field(default_factory=SandboxArtifactPolicy)

    def __post_init__(self) -> None:
        if self.network_policy is not SandboxNetworkPolicy.OFF:
            raise ContractError("Cloud M1 network policy must be off by default")
        if self.privileged_runtime_allowed is not False:
            raise ContractError("Cloud M1 privileged_runtime_allowed must be false")
        if self.host_secret_inheritance_allowed is not False:
            raise ContractError("Cloud M1 host_secret_inheritance_allowed must be false")
        if self.provider_metadata_access_allowed is not False:
            raise ContractError("Cloud M1 provider_metadata_access_allowed must be false")


# Thin canonical aliases aligning with requirements
SandboxProviderAcceptanceGate = SandboxProviderConformanceGate
VerifiedDiffEvidenceContract = VerifiedDiffEvidence

__all__ = [
    "SandboxNetworkPolicy",
    "SandboxResourceLimits",
    "SandboxFilesystemPolicy",
    "SandboxArtifactPolicy",
    "SandboxLeaseSecurityPolicy",
    "SandboxProviderAcceptanceGate",
    "VerifiedDiffEvidenceContract",
    "IsolationPrimitive",
    "SandboxArtifactManifest",
    "SandboxArtifactRef",
    "SandboxProviderAssessment",
    "SandboxProviderCapabilities",
    "REAL_SANDBOX_PROVIDER_SELECTED",
    "REAL_SANDBOX_PROVIDER_CALLS",
    "PRODUCTION_SANDBOX_CLAIM",
]
