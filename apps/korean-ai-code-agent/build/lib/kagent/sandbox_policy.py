"""Explicit sandbox policy and provider-neutral contracts for Cloud M1 (#1405).

Provides canonical value objects and acceptance gates matching threat-model requirements:
- SandboxNetworkPolicy
- SandboxResourceLimits
- SandboxFilesystemPolicy
- CloudWorkspacePathRule / CloudWorkspacePathPolicy
- SandboxArtifactPolicy
- SandboxLeaseSecurityPolicy
- SandboxProviderAcceptanceGate
- VerifiedDiffEvidenceContract
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import PurePosixPath
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
    SANDBOX_MAX_CPU_CORES,
    SANDBOX_MAX_MEMORY_MB,
    SANDBOX_MAX_DISK_MB,
    SANDBOX_MAX_PROCESS_COUNT,
    SANDBOX_ALLOWED_ARTIFACT_KINDS,
    VerifiedDiffEvidence,
    REAL_SANDBOX_PROVIDER_SELECTED,
    REAL_SANDBOX_PROVIDER_CALLS,
    PRODUCTION_SANDBOX_CLAIM,
)
from .security import redact_secrets

_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

# Cloud M1 workspace paths are POSIX-relative on the wire. Anything that cannot be
# expressed as a bounded relative prefix is refused rather than normalised into one.
_WORKSPACE_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_WORKSPACE_WILDCARD_RE = re.compile(r"[*?\[\]{}]")
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_WORKSPACE_PATH_MAX_CHARS = 512
_MAX_WORKSPACE_PATH_RULES = 64
_FORBIDDEN_WORKSPACE_PARTS = frozenset(
    {
        ".git",
        ".env",
        ".env.local",
        ".env.production",
        ".ssh",
        ".aws",
        ".gnupg",
        ".npmrc",
        ".netrc",
        "credentials",
        "credentials.json",
        "id_rsa",
        "id_ed25519",
    }
)
_FORBIDDEN_WORKSPACE_SUFFIXES = frozenset(
    {".pem", ".key", ".pfx", ".p12", ".kdbx", ".asc", ".jks", ".keystore"}
)


def _workspace_bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ContractError(f"{field_name} must be boolean")
    return value


def _workspace_relative_path(value: object, field_name: str) -> str:
    """Normalise a workspace-relative POSIX prefix, failing closed on any escape.

    Segments are validated on the raw input rather than after PurePosixPath parsing,
    because that parser quietly collapses ``a//b`` and ``./a`` into harmless-looking
    forms and the whole point of this contract is to refuse them.
    """
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    raw = value.strip()
    if not raw:
        raise ContractError(f"{field_name} must not be empty")
    if len(raw) > _WORKSPACE_PATH_MAX_CHARS:
        raise ContractError(f"{field_name} exceeds {_WORKSPACE_PATH_MAX_CHARS} characters")
    if "\\" in raw:
        raise ContractError(f"{field_name} must use POSIX separators")
    if _WORKSPACE_CONTROL_RE.search(raw):
        raise ContractError(f"{field_name} contains control characters")
    if _WORKSPACE_WILDCARD_RE.search(raw):
        raise ContractError(f"{field_name} may not contain wildcards")
    if raw.startswith("/") or raw.startswith("~"):
        raise ContractError(f"{field_name} must be workspace-relative, not absolute")
    if _WINDOWS_DRIVE_RE.match(raw):
        raise ContractError(f"{field_name} must be workspace-relative, not drive-qualified")

    segments = raw.split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        raise ContractError(
            f"{field_name} may not contain empty, current, or parent directory segments"
        )
    path = PurePosixPath(*segments)
    if path.is_absolute() or path.drive or path.root:
        raise ContractError(f"{field_name} must be workspace-relative, not absolute")
    lowered = {segment.casefold() for segment in segments}
    if lowered & _FORBIDDEN_WORKSPACE_PARTS:
        raise ContractError(f"{field_name} references credential-sensitive material")
    if any(segment.endswith(suffix) for segment in lowered for suffix in _FORBIDDEN_WORKSPACE_SUFFIXES):
        raise ContractError(f"{field_name} references a private-key-like path")
    return path.as_posix()


class SandboxNetworkPolicy(str, Enum):
    OFF = "off"
    RESTRICTED = "restricted"

    @property
    def is_deny_by_default(self) -> bool:
        return self is SandboxNetworkPolicy.OFF


@dataclass(frozen=True, slots=True)
class SandboxResourceLimits:
    # Defaults are the canonical Cloud M1 ceiling, not a second copy of it: the
    # policy the conformance gate validates against owns these numbers
    # (sandbox_conformance.SandboxSecurityPolicy), so the two cannot drift apart.
    max_cpu_cores: int = SANDBOX_MAX_CPU_CORES
    max_memory_mb: int = SANDBOX_MAX_MEMORY_MB
    max_disk_mb: int = SANDBOX_MAX_DISK_MB
    max_process_count: int = SANDBOX_MAX_PROCESS_COUNT
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
    # Coarse caller intent only. This is NOT path authority: the per-path grants in
    # CloudWorkspacePathPolicy decide reads/writes, and True here implies nothing.
    # The symlink/reparse following gate lives on that policy too, so look there when
    # mapping a provider's mount behaviour, not beside this boolean.
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


class WorkspacePathOperation(str, Enum):
    READ = "read"
    WRITE = "write"
    CREATE = "create"
    DELETE = "delete"


# Explicit, because the operation values are wire tokens and the decision field names
# are descriptive booleans; deriving one from the other by string is silent when it drifts.
_DECISION_FIELD_BY_OPERATION = {
    WorkspacePathOperation.READ: "readable",
    WorkspacePathOperation.WRITE: "writable",
    WorkspacePathOperation.CREATE: "create_allowed",
    WorkspacePathOperation.DELETE: "delete_allowed",
}


@dataclass(frozen=True, slots=True)
class CloudWorkspacePathRule:
    """One explicit, workspace-relative authority grant.

    The four operations are independent booleans: no operation is ever implied by
    another, so a read grant cannot be read as write authority and a write grant
    cannot be read as delete authority.
    """

    path_prefix_relative: str
    readable: bool = False
    writable: bool = False
    create_allowed: bool = False
    delete_allowed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "path_prefix_relative",
            _workspace_relative_path(self.path_prefix_relative, "path_prefix_relative"),
        )
        object.__setattr__(self, "readable", _workspace_bool(self.readable, "readable"))
        object.__setattr__(self, "writable", _workspace_bool(self.writable, "writable"))
        object.__setattr__(
            self, "create_allowed", _workspace_bool(self.create_allowed, "create_allowed")
        )
        object.__setattr__(
            self, "delete_allowed", _workspace_bool(self.delete_allowed, "delete_allowed")
        )
        if not self.granted_operations:
            raise ContractError(
                "a workspace path rule must grant at least one explicit operation"
            )

    @property
    def granted_operations(self) -> frozenset[WorkspacePathOperation]:
        granted = set()
        if self.readable:
            granted.add(WorkspacePathOperation.READ)
        if self.writable:
            granted.add(WorkspacePathOperation.WRITE)
        if self.create_allowed:
            granted.add(WorkspacePathOperation.CREATE)
        if self.delete_allowed:
            granted.add(WorkspacePathOperation.DELETE)
        return frozenset(granted)

    def allows(self, operation: WorkspacePathOperation) -> bool:
        return operation in self.granted_operations

    def covers(self, normalized_path: str) -> bool:
        prefix = self.path_prefix_relative
        return normalized_path == prefix or normalized_path.startswith(prefix + "/")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "cloud-workspace-path-rule.v1",
            "path_prefix_relative": self.path_prefix_relative,
            "readable": self.readable,
            "writable": self.writable,
            "create_allowed": self.create_allowed,
            "delete_allowed": self.delete_allowed,
        }


@dataclass(frozen=True, slots=True)
class CloudWorkspacePathDecision:
    """The resolved authority for exactly one workspace-relative path."""

    path: str
    readable: bool
    writable: bool
    create_allowed: bool
    delete_allowed: bool
    matched_rule_prefixes: tuple[str, ...] = ()

    @property
    def denied_operations(self) -> frozenset[WorkspacePathOperation]:
        return frozenset(
            operation
            for operation in WorkspacePathOperation
            if not self.allows(operation)
        )

    def allows(self, operation: WorkspacePathOperation) -> bool:
        if not isinstance(operation, WorkspacePathOperation):
            raise ContractError("operation must be a WorkspacePathOperation")
        return getattr(self, _DECISION_FIELD_BY_OPERATION[operation])

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "cloud-workspace-path-decision.v1",
            "path": self.path,
            "readable": self.readable,
            "writable": self.writable,
            "create_allowed": self.create_allowed,
            "delete_allowed": self.delete_allowed,
            "matched_rule_prefixes": list(self.matched_rule_prefixes),
        }


@dataclass(frozen=True, slots=True)
class CloudWorkspacePathPolicy:
    """Provider-neutral Cloud M1 path authority. Deny is the only default.

    Authority is the *intersection* of every rule covering a path, and a nested rule
    may only subtract from its ancestors. That makes resolution independent of rule
    order and makes it structurally impossible for a narrower rule to widen a
    broader denial.

    Link following is refused here rather than on SandboxFilesystemPolicy because this
    class is the boundary a provider must consult to reach a decision: an escalation
    gate that lived beside the coarse writable_workspace bool would be readable as
    intent instead of authority, which is the confusion that bool already carries.
    """

    rules: tuple[CloudWorkspacePathRule, ...] = ()

    # A lexical prefix match cannot see a symlink or a Windows reparse point, so the
    # only safe contract is that resolution never follows one. These are pinned to
    # False: they describe a limit of this authority, not a knob.
    follow_symlinks: bool = False
    follow_reparse_points: bool = False

    default_read: bool = False
    default_write: bool = False
    default_create: bool = False
    default_delete: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.rules, tuple):
            raise ContractError("rules must be a tuple of CloudWorkspacePathRule")
        for rule in self.rules:
            if not isinstance(rule, CloudWorkspacePathRule):
                raise ContractError("every rule must be a CloudWorkspacePathRule")
        if len(self.rules) > _MAX_WORKSPACE_PATH_RULES:
            raise ContractError(
                f"rules may not exceed {_MAX_WORKSPACE_PATH_RULES} entries"
            )
        for name, value in (
            ("follow_symlinks", self.follow_symlinks),
            ("follow_reparse_points", self.follow_reparse_points),
        ):
            # Identity, not truthiness: anything that is not exactly False is refused,
            # so 1 / "no" / 0 cannot smuggle link following back in.
            if value is not False:
                raise ContractError(
                    f"Cloud M1 {name} must be false; workspace authority may not "
                    "follow links or reparse points outside the workspace"
                )
        for name, value in (
            ("default_read", self.default_read),
            ("default_write", self.default_write),
            ("default_create", self.default_create),
            ("default_delete", self.default_delete),
        ):
            if value is not False:
                raise ContractError(f"Cloud M1 {name} must be false (deny is the only default)")

        by_prefix: dict[str, CloudWorkspacePathRule] = {}
        for rule in self.rules:
            duplicate = by_prefix.get(rule.path_prefix_relative)
            if duplicate is not None:
                raise ContractError(
                    f"duplicate workspace path rule: {rule.path_prefix_relative}"
                )
            by_prefix[rule.path_prefix_relative] = rule
        self._reject_widening_nested_rules(by_prefix)

    @staticmethod
    def _reject_widening_nested_rules(
        by_prefix: dict[str, CloudWorkspacePathRule],
    ) -> None:
        for ancestor in by_prefix.values():
            for descendant in by_prefix.values():
                if ancestor is descendant:
                    continue
                if not descendant.path_prefix_relative.startswith(
                    ancestor.path_prefix_relative + "/"
                ):
                    continue
                widened = descendant.granted_operations - ancestor.granted_operations
                if widened:
                    names = ", ".join(sorted(operation.value for operation in widened))
                    raise ContractError(
                        f"nested rule {descendant.path_prefix_relative} may not grant "
                        f"{names} denied by {ancestor.path_prefix_relative}"
                    )

    def decide(self, path: str) -> CloudWorkspacePathDecision:
        """Resolve authority for one path lexically.

        A permitted decision on ``workspace/link/file.txt`` is not evidence that the
        path is safe to open: this method compares normalised strings and never
        resolves what a segment points at. Keeping resolution out is why
        ``follow_symlinks`` is fixed False rather than merely defaulted False.
        """
        normalized = _workspace_relative_path(path, "path")
        matched = [rule for rule in self.rules if rule.covers(normalized)]
        granted: frozenset[WorkspacePathOperation] = frozenset()
        for index, rule in enumerate(matched):
            granted = rule.granted_operations if index == 0 else granted & rule.granted_operations
        return CloudWorkspacePathDecision(
            path=normalized,
            readable=WorkspacePathOperation.READ in granted,
            writable=WorkspacePathOperation.WRITE in granted,
            create_allowed=WorkspacePathOperation.CREATE in granted,
            delete_allowed=WorkspacePathOperation.DELETE in granted,
            matched_rule_prefixes=tuple(
                sorted(rule.path_prefix_relative for rule in matched)
            ),
        )

    def authorize(self, path: str, operation: WorkspacePathOperation) -> bool:
        return self.decide(path).allows(operation)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "cloud-workspace-path-policy.v1",
            "rules": [rule.safe_dict() for rule in sorted(self.rules, key=lambda rule: rule.path_prefix_relative)],
            "follow_symlinks": self.follow_symlinks,
            "follow_reparse_points": self.follow_reparse_points,
            "default_read": self.default_read,
            "default_write": self.default_write,
            "default_create": self.default_create,
            "default_delete": self.default_delete,
        }


@dataclass(frozen=True, slots=True)
class SandboxArtifactPolicy:
    max_artifact_bytes: int = 25 * 1024 * 1024
    max_artifact_count: int = 100
    max_terminal_output_bytes: int = 2 * 1024 * 1024
    terminal_output_sanitized: bool = True
    allowed_artifact_kinds: tuple[str, ...] = SANDBOX_ALLOWED_ARTIFACT_KINDS

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
    path_policy: CloudWorkspacePathPolicy = field(default_factory=CloudWorkspacePathPolicy)

    def __post_init__(self) -> None:
        if self.network_policy is not SandboxNetworkPolicy.OFF:
            raise ContractError("Cloud M1 network policy must be off by default")
        if self.privileged_runtime_allowed is not False:
            raise ContractError("Cloud M1 privileged_runtime_allowed must be false")
        if self.host_secret_inheritance_allowed is not False:
            raise ContractError("Cloud M1 host_secret_inheritance_allowed must be false")
        if self.provider_metadata_access_allowed is not False:
            raise ContractError("Cloud M1 provider_metadata_access_allowed must be false")
        if not isinstance(self.path_policy, CloudWorkspacePathPolicy):
            raise ContractError("path_policy must be a CloudWorkspacePathPolicy")


# Thin canonical aliases aligning with requirements
SandboxProviderAcceptanceGate = SandboxProviderConformanceGate
VerifiedDiffEvidenceContract = VerifiedDiffEvidence

from .sandbox_conformance_harness import (
    ConformanceStatus,
    SandboxProviderConformanceCase,
    SandboxProviderConformanceHarness,
    SandboxProviderConformanceReport,
    SandboxProviderConformanceResult,
    validate_lease_request_against_cloud_m1_policy,
    validate_provider_capabilities_against_cloud_m1_policy,
    validate_verified_diff_evidence,
)

__all__ = [
    "SandboxNetworkPolicy",
    "SandboxResourceLimits",
    "SandboxFilesystemPolicy",
    "WorkspacePathOperation",
    "CloudWorkspacePathRule",
    "CloudWorkspacePathDecision",
    "CloudWorkspacePathPolicy",
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
    "ConformanceStatus",
    "SandboxProviderConformanceCase",
    "SandboxProviderConformanceHarness",
    "SandboxProviderConformanceReport",
    "SandboxProviderConformanceResult",
    "validate_lease_request_against_cloud_m1_policy",
    "validate_provider_capabilities_against_cloud_m1_policy",
    "validate_verified_diff_evidence",
]

# Recorded non-claims for the Cloud M1 workspace path policy (#2755).
CLOUD_WORKSPACE_PATH_POLICY_DEFAULT_DENY = True
CLOUD_WORKSPACE_WRITABLE_WORKSPACE_BOOL_IS_AUTHORITY = False
CLOUD_WORKSPACE_ROOT_WILDCARD_EXPRESSIBLE = False
CLOUD_WORKSPACE_SYMLINK_TRAVERSAL_ALLOWED = False
CLOUD_WORKSPACE_REPARSE_TRAVERSAL_ALLOWED = False
CLOUD_WORKSPACE_TRAVERSAL_FOLLOWING_CONFIGURABLE = False
CLOUD_WORKSPACE_PATH_POLICY_PERFORMS_NO_FILESYSTEM_IO = True
CLOUD_WORKSPACE_PATH_POLICY_PERFORMS_NO_FILESYSTEM_RESOLUTION = True
CLOUD_WORKSPACE_PATH_POLICY_PROVES_SYMLINK_SAFETY = False
CLOUD_WORKSPACE_PATH_POLICY_GRANTS_NO_P01_AUTHORITY = True
CLOUD_WORKSPACE_PATH_POLICY_GRANTS_NO_B14_AUTHORITY = True
REAL_CLOUD_WORKSPACE_PATH_ENFORCEMENT_CONFIGURED = False

